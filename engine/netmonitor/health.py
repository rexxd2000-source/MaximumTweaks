"""Health analysis engine — route health scoring, packet loss analysis."""
from __future__ import annotations

from engine.netmonitor.types import (
    Hop, HopStatus, Route, RouteHealth, RouteComparison,
)


class HealthAnalyzer:
    """Determines route health from multiple factors."""

    def analyze_route(self, route: Route) -> dict:
        factors = {}
        total_score = 100

        loss = route.route_packet_loss
        if loss > 20:
            factors["packet_loss"] = {"score": 0, "detail": f"Severe loss ({loss:.0f}%)"}
            total_score -= 40
        elif loss > 10:
            factors["packet_loss"] = {"score": 30, "detail": f"High loss ({loss:.0f}%)"}
            total_score -= 25
        elif loss > 3:
            factors["packet_loss"] = {"score": 60, "detail": f"Moderate loss ({loss:.0f}%)"}
            total_score -= 10
        elif loss > 0:
            factors["packet_loss"] = {"score": 80, "detail": f"Minor loss ({loss:.0f}%)"}
            total_score -= 3
        else:
            factors["packet_loss"] = {"score": 100, "detail": "No packet loss"}

        jitter = route.route_jitter
        if jitter > 50:
            factors["jitter"] = {"score": 0, "detail": f"Extreme jitter ({jitter:.1f} ms)"}
            total_score -= 30
        elif jitter > 20:
            factors["jitter"] = {"score": 40, "detail": f"High jitter ({jitter:.1f} ms)"}
            total_score -= 15
        elif jitter > 10:
            factors["jitter"] = {"score": 60, "detail": f"Moderate jitter ({jitter:.1f} ms)"}
            total_score -= 5
        else:
            factors["jitter"] = {"score": 100, "detail": f"Low jitter ({jitter:.1f} ms)"}

        lat = route.total_latency
        if lat > 300:
            factors["latency"] = {"score": 10, "detail": f"Very high ({lat:.0f} ms)"}
            total_score -= 25
        elif lat > 150:
            factors["latency"] = {"score": 40, "detail": f"High ({lat:.0f} ms)"}
            total_score -= 15
        elif lat > 80:
            factors["latency"] = {"score": 70, "detail": f"Moderate ({lat:.0f} ms)"}
            total_score -= 5
        else:
            factors["latency"] = {"score": 100, "detail": f"Low ({lat:.0f} ms)"}

        timeouts = sum(1 for h in route.hops if h.status == HopStatus.TIMEOUT)
        # Doha/Gulf fix: isolated silent hops are often ICMP/UDP rate-limiting
        # on transit routers, NOT real path failures. Only flag when the final
        # hop (the actual endpoint) is down or several consecutive hops fail.
        max_run = 0
        run = 0
        for h in route.hops:
            if h.status == HopStatus.TIMEOUT:
                run += 1
                max_run = max(max_run, run)
            else:
                run = 0
        last_down = bool(route.hops and route.hops[-1].status == HopStatus.TIMEOUT)

        if last_down:
            factors["timeouts"] = {"score": 0, "detail": "Final hop unreachable"}
            total_score -= 35
        elif max_run >= 3:
            factors["timeouts"] = {"score": 25, "detail": f"{max_run} consecutive hops silent"}
            total_score -= 20
        elif max_run == 2 and timeouts <= 4:
            factors["timeouts"] = {"score": 70, "detail": f"2 isolated silent hops (likely rate-limited)"}
            total_score -= 4
        elif timeouts > 0:
            factors["timeouts"] = {"score": 85, "detail": f"{timeouts} isolated silent hop(s) (likely rate-limited)"}
            total_score -= 2
        else:
            factors["timeouts"] = {"score": 100, "detail": "All hops responding"}

        hop_count = len(route.hops)
        if hop_count > 20:
            factors["hop_count"] = {"score": 50, "detail": f"High hop count ({hop_count})"}
            total_score -= 10
        elif hop_count > 15:
            factors["hop_count"] = {"score": 70, "detail": f"Moderate hop count ({hop_count})"}
            total_score -= 3
        else:
            factors["hop_count"] = {"score": 100, "detail": f"Normal hop count ({hop_count})"}

        total_score = max(0, min(100, total_score))

        if total_score >= 75:
            health = RouteHealth.GOOD
        elif total_score >= 45:
            health = RouteHealth.DEGRADED
        else:
            health = RouteHealth.CRITICAL

        return {
            "health": health,
            "score": total_score,
            "factors": factors,
        }

    def analyze_packet_loss_pattern(self, route: Route) -> dict:
        """Determine if packet loss is real or ICMP rate-limiting."""
        if not route.hops:
            return {"diagnosis": "no_data", "details": []}

        details = []
        loss_segments = []

        prev_loss = 0.0
        for hop in route.hops:
            loss = hop.packet_loss
            if loss > 0:
                loss_segments.append((hop.number, loss))
            prev_loss = loss

        if not loss_segments:
            return {
                "diagnosis": "no_loss",
                "details": ["No packet loss detected along the route."],
            }

        dest_loss = route.hops[-1].packet_loss if route.hops else 0
        intermediate_losses = [
            (n, l) for n, l in loss_segments
            if n < (route.hops[-1].number if route.hops else 0)
        ]

        if intermediate_losses and dest_loss < 3:
            details.append(
                "Some intermediate hops show packet loss, but the destination "
                "does not. This is likely ICMP rate-limiting or deprioritization "
                "at those hops — not real packet loss."
            )
            return {"diagnosis": "rate_limiting", "details": details, "segments": intermediate_losses}

        sustained_loss = []
        for i, (hop_num, loss) in enumerate(loss_segments):
            later_losses = [
                l for n, l in loss_segments if n > hop_num
            ]
            if later_losses and all(l > loss * 0.7 for l in later_losses):
                sustained_loss.append((hop_num, loss))

        if sustained_loss:
            start_hop = sustained_loss[0][0]
            details.append(
                f"Packet loss begins at Hop {start_hop} and persists through "
                f"subsequent hops and the destination. This indicates real "
                f"network-level packet loss, likely occurring at or after "
                f"Hop {start_hop}."
            )
            return {"diagnosis": "real_loss", "details": details, "start_hop": start_hop, "segments": loss_segments}

        details.append(
            "Packet loss patterns suggest intermittent network congestion "
            "or ICMP deprioritization rather than sustained loss."
        )
        return {"diagnosis": "intermittent", "details": details, "segments": loss_segments}

    def analyze_latency_spikes(self, route: Route) -> list[dict]:
        """Detect where latency increases along the route."""
        spikes = []
        prev_lat = 0.0
        for hop in route.hops:
            if hop.status != HopStatus.HEALTHY:
                continue
            lat = hop.latency
            jump = lat - prev_lat
            if jump > 30 and prev_lat > 0:
                spikes.append({
                    "hop": hop.number,
                    "from_latency": prev_lat,
                    "to_latency": lat,
                    "jump": jump,
                    "severity": "high" if jump > 80 else "moderate",
                })
            prev_lat = lat
        return spikes

    def compare_routes(self, comp: RouteComparison) -> dict:
        if not comp.current or not comp.previous:
            return {"summary": "No comparison available."}

        lines = []
        if comp.hop_delta != 0:
            lines.append(f"Hop count: {comp.hop_delta:+d}")
        if abs(comp.latency_delta) > 1:
            lines.append(f"Latency: {comp.latency_delta:+.1f} ms")
        if abs(comp.jitter_delta) > 1:
            lines.append(f"Jitter: {comp.jitter_delta:+.1f} ms")
        if abs(comp.loss_delta) > 0.5:
            lines.append(f"Packet loss: {comp.loss_delta:+.1f}%")
        if comp.changed_hops:
            lines.append(f"Hops with latency changes: {', '.join(str(h) for h in comp.changed_hops)}")
        if comp.new_hops:
            lines.append(f"New hops: {', '.join(str(h) for h in comp.new_hops)}")
        if comp.removed_hops:
            lines.append(f"Removed hops: {', '.join(str(h) for h in comp.removed_hops)}")

        return {
            "summary": "\n".join(lines) if lines else "No significant changes.",
            "hop_delta": comp.hop_delta,
            "latency_delta": comp.latency_delta,
            "jitter_delta": comp.jitter_delta,
            "loss_delta": comp.loss_delta,
        }
