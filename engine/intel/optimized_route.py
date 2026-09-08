"""Estimated optimized-path model.

The estimate is heuristic for now; a later version could plug into routing
services (ExitLag, NoPing, ...) via their official APIs. The optimized route
is always labeled ESTIMATED unless real optimization data is available.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from engine.intel.traceroute import measure_route, classify_route
from engine.intel.enrichment import lookup_geo, lookup_asn
from engine.intel.models import MeasuredRoute, RouteHop


@dataclass
class OptimizedHop:
    """A single hop in an optimized route."""
    label: str = ""
    ip: str = ""
    location: str = ""
    asn: str = ""
    network: str = ""
    rtt_ms: float = 0.0
    is_endpoint: bool = False
    is_user: bool = False
    color: str = "#9C80FF"


@dataclass
class OptimizedRoute:
    """Result of optimized route analysis."""
    hops: list[OptimizedHop] = field(default_factory=list)
    total_latency_ms: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_pct: float = 0.0
    is_estimated: bool = True
    provider: str = "internal"
    confidence: str = "estimated"
    timestamp: float = 0.0
    description: str = "Estimated optimized route based on public route analysis"


class OptimizedRouteEngine:
    """Analyzes the public route and estimates an optimized path.

    Architecture:
        1. Take the public route as input
        2. Identify transit hops that could be bypassed
        3. Estimate an optimized path through fewer/more direct hops
        4. Label as ESTIMATED (never claim it's real)

    When a real routing provider (ExitLag, NoPing) is integrated,
    this engine will use their API to get actual optimized routes.
    """

    def __init__(self):
        self._provider: str = "internal"
        self._last_optimized: Optional[OptimizedRoute] = None

    @property
    def provider(self) -> str:
        return self._provider

    def set_provider(self, provider: str):
        self._provider = provider

    def compute_optimized(
        self,
        public_route: MeasuredRoute,
        destination_ip: str = "",
        user_location: tuple[float, float, str, str] = (0, 0, "", ""),
    ) -> OptimizedRoute:
        """Compute an estimated optimized route based on the public route.

        This is a HEURISTIC estimation. It identifies unnecessary transit
        hops and estimates a more direct path. The result is ALWAYS labeled
        as estimated unless a real provider is integrated.
        """
        if not public_route or not public_route.hops:
            return OptimizedRoute(
                is_estimated=True,
                provider=self._provider,
                confidence="no_data",
                timestamp=time.time(),
                description="No public route data available for optimization",
            )

        # Build user node
        user_hop = OptimizedHop(
            label="YOU",
            location=f"{user_location[2]}, {user_location[3]}" if user_location[2] else "Your Location",
            rtt_ms=0.0,
            is_user=True,
            color="#34d399",
        )

        # Build destination node
        dest_hop = OptimizedHop(
            label="GAME ENDPOINT",
            ip=destination_ip or public_route.destination_ip,
            is_endpoint=True,
            color="#8B6BFF",
        )

        # Analyze the public route for optimization opportunities
        significant_hops = self._find_significant_hops(public_route)

        if len(significant_hops) <= 2:
            # Route is already fairly direct
            optimized_hops = [user_hop] + significant_hops + [dest_hop]
        else:
            # Estimate a more direct path by keeping key transit points
            optimized_hops = [user_hop] + self._optimize_hops(significant_hops) + [dest_hop]

        # Estimate latency improvement
        public_latency = public_route.total_latency_ms
        hop_count_reduction = len(public_route.hops) - len(optimized_hops)
        estimated_improvement = max(0, hop_count_reduction * 5)  # ~5ms per bypassed hop
        estimated_latency = max(0, public_latency - estimated_improvement)

        # Set RTT values
        if len(optimized_hops) > 2:
            segment_rtt = estimated_latency / max(1, len(optimized_hops) - 2)
            for hop in optimized_hops[1:-1]:
                hop.rtt_ms = segment_rtt

        for hop in optimized_hops:
            if hop.ip:
                try:
                    geo = lookup_geo(hop.ip)
                    if geo and geo.city:
                        hop.location = f"{geo.city}, {geo.country_code}"
                    asn_info = lookup_asn(hop.ip)
                    if asn_info and asn_info.asn:
                        hop.asn = f"AS{asn_info.asn}"
                        hop.network = asn_info.name
                except Exception:
                    pass

        result = OptimizedRoute(
            hops=optimized_hops,
            total_latency_ms=estimated_latency,
            jitter_ms=public_route.jitter_ms * 0.7,
            packet_loss_pct=public_route.packet_loss_pct * 0.3,
            is_estimated=True,
            provider=self._provider,
            confidence="estimated",
            timestamp=time.time(),
            description=f"Estimated route bypassing {hop_count_reduction} transit hops",
        )

        self._last_optimized = result
        return result

    def _find_significant_hops(self, route: MeasuredRoute) -> list[OptimizedHop]:
        """Extract the significant hops from a route (skip local/private)."""
        significant = []
        for hop in route.hops:
            if hop.ip in ("0.0.0.0", "127.0.0.1", "::1", ""):
                continue
            if hop.ip.startswith("10.") or hop.ip.startswith("192.168."):
                continue

            location = ""
            if hop.geo:
                parts = []
                if hop.geo.city:
                    parts.append(hop.geo.city)
                if hop.geo.country_code:
                    parts.append(hop.geo.country_code)
                location = ", ".join(parts)

            asn_str = ""
            network = ""
            if hop.asn and hop.asn.asn:
                asn_str = f"AS{hop.asn.asn}"
                network = hop.asn.name

            oh = OptimizedHop(
                label=hop.ip,
                ip=hop.ip,
                location=location,
                asn=asn_str,
                network=network,
                rtt_ms=hop.rtt_ms,
                color="#60a5fa",
            )
            significant.append(oh)

        return significant

    def _optimize_hops(self, hops: list[OptimizedHop]) -> list[OptimizedHop]:
        """Estimate a more direct path by selecting key transit points."""
        if len(hops) <= 3:
            return hops

        # Keep: first hop (ISP gateway), last significant hop (near destination),
        # and 1-2 middle hops that represent major network transitions
        result = []
        result.append(hops[0])  # ISP gateway

        # Find hops with significant location changes
        prev_location = hops[0].location
        for hop in hops[1:-1]:
            if hop.location and hop.location != prev_location:
                result.append(hop)
                prev_location = hop.location
                if len(result) >= 4:  # Max 4 optimized hops
                    break

        if len(result) < 4 and len(hops) > 2:
            result.append(hops[-1])  # Last hop before destination

        return result

    def get_comparison(
        self,
        public_route: MeasuredRoute,
        optimized_route: OptimizedRoute,
    ) -> dict:
        """Compute comparison metrics between public and optimized routes."""
        pub_latency = public_route.total_latency_ms if public_route else 0
        opt_latency = optimized_route.total_latency_ms if optimized_route else 0
        pub_jitter = public_route.jitter_ms if public_route else 0
        opt_jitter = optimized_route.jitter_ms if optimized_route else 0
        pub_loss = public_route.packet_loss_pct if public_route else 0
        opt_loss = optimized_route.packet_loss_pct if optimized_route else 0

        return {
            "public_latency": pub_latency,
            "optimized_latency": opt_latency,
            "latency_improvement": pub_latency - opt_latency,
            "public_jitter": pub_jitter,
            "optimized_jitter": opt_jitter,
            "jitter_improvement": pub_jitter - opt_jitter,
            "public_loss": pub_loss,
            "optimized_loss": opt_loss,
            "loss_improvement": pub_loss - opt_loss,
            "public_hops": public_route.hop_count if public_route else 0,
            "optimized_hops": len(optimized_route.hops) if optimized_route else 0,
            "is_estimated": optimized_route.is_estimated if optimized_route else True,
        }
