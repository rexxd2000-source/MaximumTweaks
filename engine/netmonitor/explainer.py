"""Explanation engine — human-readable route analysis."""
from __future__ import annotations

from engine.netmonitor.types import (
    Hop, HopRole, HopStatus, MonitorState, Route, RouteHealth,
)
from engine.netmonitor.health import HealthAnalyzer


class RouteExplainer:
    def __init__(self):
        self._health = HealthAnalyzer()

    def explain_route(self, route: Route, state: MonitorState = None) -> str:
        if not route.hops:
            return "No route data available."

        parts = []

        dest_name = route.destination
        parts.append(f"Route to {dest_name} ({len(route.hops)} hops, "
                     f"{route.total_latency:.0f} ms avg).\n")

        segments = self._identify_segments(route)
        if segments:
            parts.append(self._explain_segments(segments, route))

        health_result = self._health.analyze_route(route)
        parts.append(self._explain_health(health_result, route))

        loss_analysis = self._health.analyze_packet_loss_pattern(route)
        if loss_analysis.get("diagnosis") != "no_loss":
            parts.append(self._explain_loss(loss_analysis, route))

        spikes = self._health.analyze_latency_spikes(route)
        if spikes:
            parts.append(self._explain_spikes(spikes))

        if state and state.previous_route:
            comp = state.comparison
            comp_result = self._health.compare_routes(comp)
            if comp_result.get("summary") != "No significant changes.":
                parts.append(f"Route comparison vs previous:\n{comp_result['summary']}")

        return "\n\n".join(parts)

    def _identify_segments(self, route: Route) -> list[dict]:
        segments = []
        current_seg = None

        for hop in route.hops:
            role = hop.role
            if role in (HopRole.LOCAL, HopRole.GATEWAY):
                seg_type = "local"
            elif role in (HopRole.ISP_ACCESS, HopRole.ISP_CORE):
                seg_type = "isp"
            elif role in (HopRole.TRANSIT, HopRole.PEERING):
                seg_type = "transit"
            elif role == HopRole.CDN:
                seg_type = "cdn"
            elif role == HopRole.DESTINATION:
                seg_type = "destination"
            else:
                seg_type = "unknown"

            if current_seg is None or current_seg["type"] != seg_type:
                if current_seg:
                    current_seg["end"] = hop.number - 1
                    segments.append(current_seg)
                current_seg = {
                    "type": seg_type,
                    "start": hop.number,
                    "end": hop.number,
                    "hops": [hop],
                    "city": hop.geo.city,
                    "org": hop.network.as_org or hop.network.isp,
                    "avg_lat": hop.latency,
                }
            else:
                current_seg["end"] = hop.number
                current_seg["hops"].append(hop)
                if hop.latency > current_seg["avg_lat"]:
                    current_seg["avg_lat"] = hop.latency

        if current_seg:
            current_seg["end"] = len(route.hops)
            segments.append(current_seg)

        return segments

    def _explain_segments(self, segments: list[dict], route: Route) -> str:
        parts = []
        for seg in segments:
            seg_type = seg["type"]
            hop_range = f"Hops {seg['start']}-{seg['end']}"
            loc = seg.get("city", "")
            org = seg.get("org", "")
            loc_str = f" ({loc})" if loc else ""
            org_str = f" — {org}" if org else ""

            if seg_type == "local":
                parts.append(f"Your local network: {hop_range}{org_str}.")
            elif seg_type == "isp":
                parts.append(
                    f"Your ISP ({org or 'unknown'}){loc_str}: {hop_range}, "
                    f"up to {seg['avg_lat']:.0f} ms."
                )
            elif seg_type == "transit":
                parts.append(
                    f"Transit/peering network{loc_str}{org_str}: {hop_range}, "
                    f"up to {seg['avg_lat']:.0f} ms."
                )
            elif seg_type == "cdn":
                parts.append(
                    f"CDN/edge network{org_str}{loc_str}: {hop_range}."
                )
            elif seg_type == "destination":
                parts.append(
                    f"Destination: {hop_range}{loc_str}{org_str}, "
                    f"{seg['avg_lat']:.0f} ms."
                )
            elif seg_type == "unknown":
                parts.append(
                    f"Network segment{org_str}{loc_str}: {hop_range}."
                )

        return " ".join(parts)

    def _explain_health(self, result: dict, route: Route) -> str:
        health = result["health"]
        score = result["score"]
        factors = result["factors"]

        status_map = {
            RouteHealth.GOOD: "GOOD",
            RouteHealth.DEGRADED: "DEGRADED",
            RouteHealth.CRITICAL: "CRITICAL",
            RouteHealth.UNKNOWN: "UNKNOWN",
        }
        parts = [f"Route Health: {status_map[health]} ({score}/100)"]

        for name, info in factors.items():
            parts.append(f"  {info['detail']}")

        return "\n".join(parts)

    def _explain_loss(self, analysis: dict, route: Route) -> str:
        diagnosis = analysis.get("diagnosis", "")
        details = analysis.get("details", [])
        lines = ["Packet Loss Analysis:"]
        lines.extend(details)
        return "\n".join(lines)

    def _explain_spikes(self, spikes: list[dict]) -> str:
        lines = ["Latency Increases:"]
        for spike in spikes:
            severity = "significant" if spike["severity"] == "high" else "moderate"
            lines.append(
                f"  Hop {spike['hop']}: {spike['from_latency']:.0f} → "
                f"{spike['to_latency']:.0f} ms (+{spike['jump']:.0f} ms, {severity})"
            )
        return "\n".join(lines)

    def explain_destination(self, route: Route) -> str:
        if not route.hops:
            return "No destination data."
        dest = route.hops[-1]
        parts = [f"Destination: {route.destination}"]
        if dest.ip:
            parts.append(f"IP: {dest.ip}")
        if dest.hostname and dest.hostname != route.destination:
            parts.append(f"Hostname: {dest.hostname}")
        if dest.network.asn:
            parts.append(f"ASN: AS{dest.network.asn} ({dest.network.as_org})")
        if dest.location_label and dest.location_label != dest.location_str:
            parts.append(f"Location: {dest.location_label} (approx.)")
        elif dest.location_str:
            parts.append(f"Location: {dest.location_str}")
        parts.append(f"Latency: {dest.latency:.0f} ms")
        parts.append(f"Packet Loss: {dest.packet_loss:.0f}%")
        return "\n".join(parts)

    def basic_view(self, route: Route, state: MonitorState = None) -> dict:
        health = self._health.analyze_route(route)
        dest = route.hops[-1] if route.hops else None
        return {
            "destination": route.destination,
            "destination_ip": route.destination_ip,
            "hops": route.total_hops,
            "latency": f"{route.total_latency:.0f} ms",
            "jitter": f"{route.route_jitter:.1f} ms",
            "packet_loss": f"{route.route_packet_loss:.0f}%",
            "health": health["health"].value.upper(),
            "health_score": health["score"],
            "path": route.path_summary,
            "explanation": self.explain_route(route, state),
        }

    def advanced_view(self, route: Route, state: MonitorState = None) -> dict:
        basic = self.basic_view(route, state)
        loss_analysis = self._health.analyze_packet_loss_pattern(route)
        spikes = self._health.analyze_latency_spikes(route)
        basic["loss_analysis"] = loss_analysis
        basic["latency_spikes"] = spikes
        basic["health_factors"] = self._health.analyze_route(route)["factors"]
        return basic
