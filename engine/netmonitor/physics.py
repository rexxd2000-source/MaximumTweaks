"""Speed-of-light plausibility gate for reported route latency.

Network latency can never beat physics: a round trip over a fiber path of
total length D must take at least

    RTT_min = 2 * D / c_glass,   c_glass ~= 200 000 km/s   (=> 0.01 ms per
    kilometer of fiber round trip).

We estimate the fiber path from the great-circle distance between the user
and the destination times a routing winding factor (subsea/international
paths rarely follow a straight line).

A measured total that is *below* the floor is physically impossible for that
destination — it signals a wrong geo lookup, an anycast edge mispin, or a
fabricated/fallback metric. Instead of displaying that impossible number we
surface the floor as the honest physical minimum and flag the measurement.
"""
from __future__ import annotations

import math
from typing import Optional

from engine.netmonitor.types import GeoPoint, Route

# Speed of light in optical fiber (km/s): ~200 000 km/s.
C_GLASS_KMS = 200_000.0
# Conservative winding factor for real fiber routes (never < 1.0).
FIBER_WINDING = 1.35
# Flag when measured < this fraction of the floor (never 1.0 — the floor is
# the absolute best case, real networks sit above it).
IMPLAUSIBLE_RATIO = 0.85


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometers."""
    r_earth = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r_earth * math.asin(min(1.0, math.sqrt(a)))


def fiber_path_km(src: GeoPoint, dst: GeoPoint) -> float:
    """Estimated fiber length between two points (km)."""
    d = haversine_km(src.latitude, src.longitude, dst.latitude, dst.longitude)
    if d <= 0:
        return 0.0
    # Very short local hops keep the direct distance; long paths wind.
    return d * max(1.0, FIBER_WINDING - 0.35 * min(0.35, d / 10000.0))


def min_rtt_ms(distance_km: float) -> float:
    """Physical round-trip floor: 2 * D / c_glass (ms)."""
    if distance_km <= 0:
        return 0.0
    return 2 * distance_km / C_GLASS_KMS * 1000.0


def latency_floor_ms(src: GeoPoint, dst: GeoPoint) -> tuple[float, float]:
    """Return (floor_ms, fiber_distance_km) for the src→dst path."""
    dist = fiber_path_km(src, dst)
    return min_rtt_ms(dist), dist


def validate_total_latency(
    measured_ms: float,
    src: GeoPoint,
    dst: GeoPoint,
) -> tuple[bool, str, float, float]:
    """Gate a measured total latency against the physical floor.

    Returns (implausible, reason, floor_ms, fiber_distance_km). A measured
    value far below the fiber floor is impossible for that destination and
    is rejected — the caller surfaces the floor as the honest minimum.
    """
    floor_ms, dist = latency_floor_ms(src, dst)
    if floor_ms <= 0 or measured_ms <= 0:
        return False, "", floor_ms, dist
    if measured_ms < floor_ms * IMPLAUSIBLE_RATIO:
        reason = (
            f"{measured_ms:.0f} ms is below the {floor_ms:.0f} ms "
            f"speed-of-light floor for ~{dist:.0f} km of fiber"
        )
        return True, reason, floor_ms, dist
    return False, "", floor_ms, dist


def enforce_route_physics(
    route: Route,
    user_loc: Optional[GeoPoint] = None,
    dest_geo: Optional[GeoPoint] = None,
) -> None:
    """Fill Route physics fields: floor, distance, implausibility.

    Uses the live measured total (or fallback total) as the measured value.
    Kept non-destructive: the raw measurement stays in `total_latency`, the
    honest floor is available for display, and `physics_implausible` tells the
    UI to prefer the floor over the impossible number.
    """
    route.latency_floor_ms = 0.0
    route.fiber_distance_km = 0.0
    route.physics_implausible = False
    route.physics_reason = ""

    if route.hops and route.hops[-1].network.network_type == "anycast_edge":
        # Anycast endpoint (e.g. traced google.com): the geo-DB location is
        # only a guess of where the traffic might egress, never the actual
        # server — a distance-based floor against it would be fabricated.
        return

    src = user_loc or _default_user_loc()
    dst = dest_geo or _route_dest_geo(route)
    if src is None or dst is None or not dst.latitude or not dst.longitude:
        # Unknown destination geo — cannot gate, leave as-is.
        if dst is None:
            return
    if not (dst.latitude or dst.longitude):
        return

    impl, reason, floor_ms, dist = validate_total_latency(
        route.total_latency, src, dst
    )
    route.latency_floor_ms = floor_ms
    route.fiber_distance_km = dist
    route.physics_implausible = impl
    route.physics_reason = reason


_USER_LOC_CACHE: tuple[Optional[GeoPoint], float] = (None, 0.0)


def user_geo_point() -> Optional[GeoPoint]:
    """Public wrapper for the cached user anchor (None when unresolvable —
    never a (0,0) placeholder)."""
    return _default_user_loc()


def _default_user_loc() -> Optional[GeoPoint]:
    """Resolve the user's own geolocation once (cached 1h)."""
    global _USER_LOC_CACHE
    import time

    now = time.time()
    cached, ts = _USER_LOC_CACHE
    if cached is not None and now - ts < 3600:
        return cached
    try:
        from engine.netmonitor.resolver import get_public_geo

        geo = get_public_geo()
        if not (geo.latitude or geo.longitude):
            return None
        point = GeoPoint(
            latitude=geo.latitude,
            longitude=geo.longitude,
            city=geo.city,
            country=geo.country,
        )
        _USER_LOC_CACHE = (point, now)
        return point
    except Exception:
        return None


def _route_dest_geo(route: Route) -> Optional[GeoPoint]:
    """Destination geo for the route (last-hop geo, falling back to a stored
    destination location on the route)."""
    if route.hops:
        h = route.hops[-1]
        if h.geo and (h.geo.latitude or h.geo.longitude):
            return GeoPoint(
                latitude=h.geo.latitude,
                longitude=h.geo.longitude,
                city=h.geo.city,
                country=h.geo.country,
            )
    return None


def validate_hop_geo(hop, anchor: Optional[GeoPoint]) -> bool:
    """Physically gate a single hop's geo against its measured latency.

    A probe that reached an *advertised* city faster than light can travel
    there means the geo label is wrong for that IP (typical of cloud ranges
    and proxied/relay hops), not that the clock lied. Marks the hop's geo
    unverified + explains why. Returns True when the label is plausible.
    """
    if anchor is None or not anchor.latitude or not anchor.longitude:
        return True
    geo = getattr(hop, "geo", None)
    if geo is None or not (geo.latitude or geo.longitude):
        return True
    for p in hop.probes:
        if p.direction == "sent" and p.ms is not None and p.sent_time is not None:
            measured = p.ms
            break
    else:
        measured = hop.latency
    if not measured or measured <= 0:
        return True
    dist = fiber_path_km(anchor, geo)
    floor = min_rtt_ms(dist)
    if floor <= 0:
        return True
    if measured < floor * IMPLAUSIBLE_RATIO:
        geo.verified = False
        geo.hint = (
            f"reached in {measured:.0f} ms < {floor:.0f} ms light-time for "
            f"~{dist:.0f} km — geolocation rejected"
        )
        return False
    return True


def validate_dest_geo(route, anchor: Optional[GeoPoint]) -> None:
    """Destination region-consistency check.

    A probe-silent destination has no measured latency, so the fiber floor
    can't gate it. Instead we cross-check its advertised location against the
    last public transit hop the trace actually proved: a multi-thousand-km
    claim with a nearby transit exit (or a *different country* than the path
    actually ran through) is flagged approximate so the map/labels never
    present a guessed "Doha" for a server the path showed is in California."""
    if not route.hops:
        return
    dest = route.hops[-1]
    if not dest.is_last_hop or dest.latency > 0:
        return
    dg = getattr(dest, "geo", None)
    if dg is None or not (dg.latitude or dg.longitude):
        return
    public = [
        h for h in route.hops
        if h.ip and not h.network.is_private
        and h.geo and (h.geo.latitude or h.geo.longitude)
        and h.number != dest.number
    ]
    if not public:
        return
    prev = public[-1]
    pg = prev.geo
    d_km = haversine_km(pg.latitude, pg.longitude, dg.latitude, dg.longitude)
    if d_km <= 1200 or not (pg.city or pg.country):
        return
    zone = f"{prev.city} ({prev.country})" if prev.city else prev.country
    dg.approximate = True
    dg.hint = (
        f"destination region inconsistent with transit ({d_km:.0f} km from "
        f"{zone}) — location unverified"
    )