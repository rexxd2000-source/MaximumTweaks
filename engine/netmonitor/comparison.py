"""Public-internet vs tunnel (optimized) route bridging for Route Analyzer.

Behavior:
  * The "optimized" side is ONLY ever a REAL measurement: a traceroute that ran
    through an active GPN/VPN tunnel (stored as ``Route.tunnel_route``).
  * When no tunnel instance actively carries the game-server route, the
    optimized side is entirely absent (``has_tunnel=False``) — no static or
    heuristic mocks are ever displayed as optimization.
"""
from __future__ import annotations

import ipaddress
import re

from engine.netmonitor.types import Hop, HopStatus, ProbeMethod, Route
from ui.route_visualization import RouteNode


# ────────────────────────────────────────────────────────────────────────
#  Hop label helpers
# ────────────────────────────────────────────────────────────────────────
def _is_private_ip(ip: str) -> bool:
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def _is_local_hop(hop: Hop) -> bool:
    return bool(hop.network.is_private or hop.network.is_cgnat) or _is_private_ip(hop.ip)


def _user_anchor() -> tuple[str, str]:
    """The user's own city/country from the cached physics anchor (1 h).
    Never a network call per poll — None/empty when unresolvable."""
    try:
        from engine.netmonitor.physics import user_geo_point
        p = user_geo_point()
    except Exception:
        return "", ""
    if p and (p.city or p.country):
        return p.city, p.country
    return "", ""


def _domain_from_hostname(hostname: str) -> str:
    """Last two DNS labels, e.g. '100-127-2-186.ip.ahisp.co.za' -> 'ahisp.co.za'."""
    if not hostname:
        return ""
    labels = [p for p in hostname.lower().split(".") if p]
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return hostname


def _is_cgnat_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def _premium_location(hop: Hop, u_city: str, u_country: str) -> str:
    """City/country labels that stay honest:
      * private/local hops ARE in the user's own building/city, but ip-api's
        city for SA ISP ranges is registered-office noise (it flips between
        "Johannesburg" and "Port Elizabeth" for the same ranges) — unless the
        ISP's OWN signals resolved a real PoP city (reverse-DNS code / prefix
        table), local hops are labeled individually, never with a repeated
        generic "Local network" filler: the home gateway is "Your Router",
        CGNAT hops show their IP (+ hostname domain), unresolved hops show the
        raw IP/hostname until their city is hand-verified;
      * a cloud/backbone entry hop carries a measured-path direction note
        ("leaves South Africa") only when its own latency proves it is still
        in the user's country — never a geo-DB guess for an anycast range.
    """
    if _is_local_hop(hop):
        src = getattr(hop.geo, "city_source", "") or ""
        city = hop.geo.city if hop.geo else ""
        if city and src in ("hostname", "isp_prefix"):
            province = hop.geo.region or ""
            country = hop.geo.country or u_country or ""
            return f"{city}, {province} ({country})" if province and country else (f"{city}, {country}" if country else city)
        if hop.number == 1 and not hop.network.is_cgnat:
            return "Your Router"
        if hop.network.is_cgnat or _is_cgnat_ip(hop.ip or ""):
            dom = _domain_from_hostname(hop.hostname or "")
            return f"{hop.ip} \u00b7 {dom}" if dom and dom != (hop.ip or "") else (hop.ip or "CGNAT hop")
        return hop.display_name or hop.ip or "local hop"
    label = _hop_location(hop)
    if (
        label
        and u_country
        and "entered cloud" in (hop.probes.raw_hint or "")
        and 0 < hop.latency < 45
    ):
        return f"{label} \u00b7 leaves {u_country}"
    return label
def _hop_label(hop: Hop) -> str:
    if hop.is_last_hop:
        return "SERVER"
    if hop.status == HopStatus.HEALTHY:
        return hop.hostname or hop.ip or f"H{hop.number}"
    if hop.ip:
        return hop.ip
    return f"H{hop.number}"


def _hop_location(hop: Hop) -> str:
    return hop.location_label or ", ".join(
        p for p in (hop.geo.city, hop.geo.country) if p
    )


def _hop_asn(hop: Hop) -> str:
    if hop.network.asn:
        org = hop.network.as_org or hop.network.network_name or ""
        return f"AS{hop.network.asn} {org}".strip()
    return ""


# ────────────────────────────────────────────────────────────────────────
#  Node lists for the visualization widget
# ────────────────────────────────────────────────────────────────────────
def _public_nodes(route: Route, destination_ip: str, user_loc: tuple) -> list[RouteNode]:
    u_city = (user_loc[2] if user_loc and len(user_loc) > 2 else "") or ""
    u_country = (user_loc[3] if user_loc and len(user_loc) > 3 else "") or ""
    if not u_city and not u_country:
        u_city, u_country = _user_anchor()
    nodes: list[RouteNode] = [
        RouteNode(
            label="YOU",
            ip="",
            # ip-api's city for the user's own IP is the ISP's registered office
            # (measured: it flips Johannesburg/Port Elizabeth on the same IP) —
            # anchor at country level, never a guessed city.
            location=f"{u_country}" if u_country else "Your Location",
            rtt_ms=0.0,
            is_user=True,
            color="#34d399",
        )
    ]
    for hop in route.hops:
        if hop.is_last_hop and hop.ip and hop.ip == (destination_ip or route.destination_ip):
            nodes.append(RouteNode(
                label="SERVER",
                ip=hop.ip,
                location=_hop_location(hop),
                asn=_hop_asn(hop),
                network=hop.network.network_name or hop.network.as_org or "",
                rtt_ms=hop.latency,
                is_endpoint=True,
                color="#8B6BFF",
            ))
        else:
            nodes.append(RouteNode(
                label=_hop_label(hop),
                ip=hop.ip,
                location=_premium_location(hop, u_city, u_country),
                asn=_hop_asn(hop),
                network=hop.network.network_name or hop.network.as_org or "",
                rtt_ms=hop.latency,
                color="#60a5fa",
            ))
    # The honest backbone gap: past the last real (answering) hop the path is
    # unknown hop-by-hop — the game's foreign routers drop every traceroute-
    # class probe by design (ICMP/UDP/TCP TTL-exceeded) once past the exit
    # edge. So instead of a false straight "SA -> server" jump, the correct
    # route renders as: known SA hops -> ONE outside region + its honest
    # timing (derived from the game's own end-to-end RTT minus the SA exit)
    # -> the server. No fabricated/borrowed transit routers are ever shown.
    dest_country = ""
    if route.hops:
        dest_country = (route.hops[-1].geo.country or "") if route.hops[-1].geo else ""
    international = bool(dest_country and u_country and dest_country.lower() != u_country.lower())
    silent = route.probe_silent_endpoint or any(
        "entered cloud" in (h.probes.raw_hint or "") for h in route.hops
    )
    if silent or international:
        frontier = -1
        for i, node in enumerate(nodes):
            if not node.is_endpoint and node.ip:
                frontier = i
        if frontier >= 0:
            edge_ms = float(nodes[frontier].rtt_ms or 0.0)
            total_ms = float(route.total_latency or 0.0)
            outside_ms = max(total_ms - edge_ms, 0.0)
            # The city/region anchor for the destination lives on the SERVER /
            # BGP-provider node — it must appear ONCE on the diagram, not here
            # (previously _zone_label duplicated "GCP me-central1 → Doha, ...").
            loc = (
                f"~{outside_ms:.0f} ms outside {u_country} "
                f"(of the {total_ms:.0f} ms in-game total)"
                if total_ms > 0
                else "internet backbone"
            )
            out_node = RouteNode(
                label=(
                    "CLOUD ZONE"
                    if route.probe_silent_endpoint
                    else f"OUTSIDE {_cc(u_country)}"
                ),
                ip="",
                location=loc,
                asn="undersea + backbone" if outside_ms > 0 else "probes dropped by design",
                network=(
                    "measured end-to-end from the game's live RTT; the foreign "
                    "routers past the exit edge do not answer traceroute probes"
                ),
                rtt_ms=outside_ms,
                color="#FFB454",
                is_context=True,
            )
            mut = list(nodes)
            mut.insert(frontier + 1, out_node)
            nodes = mut

            # BGP routing-data path for the international leg — real ASN/
            # prefix registrations, honestly labeled as BGP-sourced, never
            # presented as live traceroute latency (rtt_ms stays 0).
            bgp = route.bgp_path or {}
            if bgp.get("resolved") and bgp.get("dest"):
                bnodes = []
                isp = bgp.get("isp") or {}
                if isp.get("asn"):
                    bnodes.append(RouteNode(
                        label="SA ISP",
                        ip="",
                        location=(
                            f"AS{isp['asn']} {isp.get('name') or ''}".strip()
                            if isp.get("name")
                            else f"AS{isp['asn']}"
                        ),
                        asn=f"AS{isp['asn']}",
                        network=(
                            f"{bgp.get('source') or 'BGP routing data'} · "
                            "your ISP's AS hands your traffic to the "
                            "cloud provider's own network"
                        ),
                        rtt_ms=0.0,
                        color="#14b8a6",
                        is_context=True,
                    ))
                dest = bgp.get("dest") or {}
                if dest.get("asn"):
                    dname = str(dest.get("name") or "PROVIDER")
                    # Country only on the context node: the authoritative city
                    # (e.g. Doha) is already on the SERVER node — repeating it
                    # here was the redundant "third Doha" the docs flagged.
                    dloc = str(dest.get("country") or "")
                    bnodes.append(RouteNode(
                        label=dname[:16].upper(),
                        ip="",
                        location=dloc,
                        asn=f"AS{dest['asn']}",
                        network=(
                            f"{bgp.get('source') or 'BGP routing data'} · "
                            f"AS{dest['asn']} announces the destination "
                            "prefix; the path enters its own network at the "
                            "SA exit and is carried inside a single AS to "
                            "the server region — no third-party transit, "
                            "which is why per-hop probes past the exit time "
                            "out. Shows the routing path, not per-hop "
                            "latency; the outside-ms figure is live-measured."
                        ),
                        rtt_ms=0.0,
                        color="#14b8a6",
                        is_context=True,
                    ))
                if bnodes:
                    mut = list(nodes)
                    for off, bn in enumerate(bnodes, start=1):
                        mut.insert(frontier + 1 + off, bn)
                    nodes = mut
    # Only append an explicit SERVER node if the route did not already end there.
    if not (route.hops and route.hops[-1].is_last_hop
            and route.hops[-1].ip == (destination_ip or route.destination_ip)):
        nodes.append(RouteNode(
            label="SERVER",
            ip=destination_ip or route.destination,
            location=_route_dest_label(route),
            rtt_ms=route.total_latency,
            is_endpoint=True,
            color="#8B6BFF",
        ))
    return nodes


def _route_dest_label(route: Route) -> str:
    if route.hops:
        h = route.hops[-1]
        if h.geo and (h.geo.city or h.geo.country):
            return ", ".join(p for p in (h.geo.city, h.geo.country) if p)
        if h.network.network_name or h.network.as_org:
            return h.network.network_name or h.network.as_org or ""
    return ""


def _cc(country: str) -> str:
    """Short country code-ish label for the outside node (e.g. 'SA')."""
    if not country:
        return "INTERNATIONAL"
    common = {
        "south africa": "SA", "united states": "US", "united kingdom": "UK",
        "germany": "DE", "france": "FR", "netherlands": "NL", "qatar": "QA",
    }
    key = country.strip().lower()
    if key in common:
        return common[key]
    parts = [w for w in key.split() if w]
    if len(parts) >= 2:
        return "".join(w[0].upper() for w in parts[:2])
    return country[:2].upper()


def _zone_label(route: Route) -> str:
    """Zone title from the SERVER hop's provider region (authoritative cloudmap
    scope, e.g. 'GCP me-central1') plus its city/country anchor."""
    dest = route.hops[-1] if route.hops else None
    geo = getattr(dest, "geo", None) if dest else None
    parts = []
    if geo and geo.hint:
        m = re.search(r"\((GCP|AWS)\s+([^()]*)\)", geo.hint, re.IGNORECASE)
        if m:
            parts.append(f"{m.group(1).upper()} {m.group(2).strip()}")
    if geo and geo.city:
        anchor = geo.city
        if geo.region:
            anchor += f", {geo.region}"
        if geo.country:
            anchor += f", {geo.country}"
        parts.append(anchor)
    if not parts:
        return "internet backbone"
    return " \u2192 ".join(parts)


def _tunnel_nodes(
    tunnel_route: Route, destination_ip: str, user_loc: tuple, tunnel: dict
) -> list[RouteNode]:
    """Real nodes as measured through the active tunnel."""
    nodes: list[RouteNode] = [
        RouteNode(
            label="YOU",
            ip="",
            location=f"{user_loc[2]}, {user_loc[3]}" if user_loc[2] else "Your Location",
            rtt_ms=0.0,
            is_user=True,
            color="#34d399",
        )
    ]
    entry_name = tunnel.get("name", "")
    for i, hop in enumerate(tunnel_route.hops):
        is_first = i == 0
        if hop.is_last_hop and hop.ip and hop.ip == (destination_ip or tunnel_route.destination_ip):
            nodes.append(RouteNode(
                label="SERVER",
                ip=hop.ip,
                location=_hop_location(hop),
                asn=_hop_asn(hop),
                network=hop.network.network_name or hop.network.as_org or "",
                rtt_ms=hop.latency,
                is_endpoint=True,
                color="#8B6BFF",
            ))
        else:
            label = _hop_label(hop)
            if is_first and entry_name:
                label = "TUNNEL"
            nodes.append(RouteNode(
                label=label,
                ip=hop.ip,
                location=_hop_location(hop),
                asn=_hop_asn(hop),
                network=hop.network.network_name or hop.network.as_org or "",
                rtt_ms=hop.latency,
                color="#9C80FF",
            ))
    if not (tunnel_route.hops and tunnel_route.hops[-1].is_last_hop
            and tunnel_route.hops[-1].ip == (destination_ip or tunnel_route.destination_ip)):
        nodes.append(RouteNode(
            label="SERVER",
            ip=destination_ip or tunnel_route.destination,
            rtt_ms=tunnel_route.total_latency,
            is_endpoint=True,
            color="#8B6BFF",
        ))
    return nodes


# ────────────────────────────────────────────────────────────────────────
#  Real diff between the two measured routes
# ────────────────────────────────────────────────────────────────────────
def _real_comparison(route: Route, tunnel_route: Route) -> dict:
    pub_latency = route.total_latency
    opt_latency = tunnel_route.total_latency
    pub_jitter = route.route_jitter
    opt_jitter = tunnel_route.route_jitter
    pub_loss = route.route_packet_loss
    opt_loss = tunnel_route.route_packet_loss
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
        "public_hops": route.total_hops or len(route.hops),
        "optimized_hops": tunnel_route.total_hops or len(tunnel_route.hops),
        "is_estimated": False,
    }


# ────────────────────────────────────────────────────────────────────────
#  Main entry point
# ────────────────────────────────────────────────────────────────────────
def build_route_comparison(
    route: Route,
    destination_ip: str = "",
    user_loc: tuple = (0.0, 0.0, "", ""),
) -> dict:
    """Turn a traced Route into public/tunnel node data.

    Returns dict with:
      public_nodes, optimized_nodes        -> feed RouteVisualizationWidget.set_nodes()
      tunnel, has_tunnel                   -> whether a real tunnel path exists
      comparison                           -> stats bar data
      public_latency_ms                    -> headline number
      estimated, description, provider     -> provenance labels
    """
    dest_ip = destination_ip or route.destination_ip
    public_nodes = _public_nodes(route, dest_ip, user_loc)
    public_latency = route.total_latency
    public_lat = max((h.latency for h in route.hops), default=0.0)
    public_hops = route.total_hops or len(route.hops)
    u_country = (user_loc[3] if user_loc and len(user_loc) > 3 else "") or ""
    if not u_country:
        _anchor = _user_anchor()
        u_country = _anchor[1] if len(_anchor) > 1 else ""
    budget = _latency_budget(public_nodes, u_country, public_latency)

    tunnel_route = route.tunnel_route
    if tunnel_route and tunnel_route.hops:
        tunnel = route.tunnel_info or {}
        optimized_nodes = _tunnel_nodes(tunnel_route, dest_ip, user_loc, tunnel)
        comparison = _real_comparison(route, tunnel_route)
        return {
            "public_nodes": public_nodes,
            "optimized_nodes": optimized_nodes,
            "optimized_route": tunnel_route,
            "tunnel": tunnel,
            "has_tunnel": True,
            "comparison": comparison,
            "public_latency_ms": public_latency,
            "optimized_latency_ms": tunnel_route.total_latency,
            "estimated": False,
            "provider": tunnel.get("name", "tunnel"),
            "latency_budget": budget,
            "description": (
                f"Real measured path through active tunnel "
                f"'{tunnel.get('name', '')}' — {optimized_nodes and (len(optimized_nodes) - 1)} hops, "
                f"{tunnel_route.total_latency:.0f} ms"
            ),
        }

    # No active tunnel carrying this route → the optimized side is suppressed.
    return {
        "public_nodes": public_nodes,
        "optimized_nodes": [],
        "optimized_route": None,
        "tunnel": None,
        "has_tunnel": False,
        "comparison": {
            "public_latency": public_latency,
            "optimized_latency": 0.0,
            "latency_improvement": 0.0,
            "public_jitter": route.route_jitter,
            "optimized_jitter": 0.0,
            "jitter_improvement": 0.0,
            "public_loss": route.route_packet_loss,
            "optimized_loss": 0.0,
            "loss_improvement": 0.0,
            "public_hops": public_hops,
            "optimized_hops": 0,
            "is_estimated": False,
        },
        "public_latency_ms": public_latency,
        "optimized_latency_ms": 0.0,
        "estimated": False,
        "provider": "",
        "latency_budget": budget,
        "description": "No active GPN/VPN tunnel carries this route — optimized path not shown",
    }


# ────────────────────────────────────────────────────────────────────────
#  Comparison stats -> display helpers
# ────────────────────────────────────────────────────────────────────────
def _latency_budget(public_nodes: list, u_country: str, total_ms: float) -> dict:
    """Explain HOW the headline number builds up, segment by segment.

    Real hops report the latency reached AT each hop (cumulative), so each
    hop's contribution is the delta to the previous one. The outside node's
    rtt is already the outside slice (total minus the SA exit), so it is a
    pure segment. The server node is the live in-game total — the honest
    endpoint, never a hop average. This turns '150 ms' into:
      ~29 ms inside South Africa  +  ~121 ms outside  =  150 ms (live).
    """
    segs: list[dict] = []
    prev = 0.0  # cumulative before current hop
    last_hop_ms = 0.0
    last_hop_cum = 0.0
    outside_ms = 0.0
    dest_hint = ""
    for n in public_nodes:
        if getattr(n, "is_user", False):
            continue
        rtt = float(n.rtt_ms or 0.0)
        if getattr(n, "is_endpoint", False) and n.label == "SERVER":
            segs.append({
                "label": "SERVER", "ip": n.ip or "",
                "slice_ms": round(max(total_ms - prev, 0.0), 1),
                "cumulative_ms": round(total_ms, 1), "kind": "server",
            })
            prev = total_ms
            continue
        if n.label == "CLOUD ZONE" or n.label.startswith("OUTSIDE "):
            outside_ms = rtt
            segment_ms = round(rtt, 1)
            prev = round(prev + rtt, 1)
            segs.append({
                "label": n.label, "ip": n.ip or "",
                "slice_ms": segment_ms, "cumulative_ms": prev, "kind": "outside",
            })
            dest_hint = n.location or ""
            continue
        slice_ms = round(max(rtt - prev, 0.0), 1)
        segs.append({
            "label": n.label, "ip": n.ip or "",
            "slice_ms": slice_ms, "cumulative_ms": round(rtt, 1), "kind": "hop",
        })
        last_hop_ms = slice_ms
        last_hop_cum = round(rtt, 1)
        prev = rtt
    inside_ms = last_hop_cum
    summary = ""
    if total_ms > 0:
        parts = []
        if inside_ms > 0:
            parts.append(f"~{inside_ms:.0f} ms inside {u_country or 'your country'}")
        if outside_ms > 0:
            parts.append(f"{outside_ms:.0f} ms outside (undersea/backbone)")
            share = outside_ms / total_ms * 100.0
        if parts:
            summary = (
                f"How your {total_ms:.0f} ms builds: "
                + (" + ".join(parts))
                + f" = {total_ms:.0f} ms (live in-game)."
                + (
                    f" The outside leg is {share:.0f}% of your ping — "
                    "undersea/backbone cost, not your PC, not your ISP's "
                    "suburbs."
                    if outside_ms > 0
                    else " Packets stay inside your country; the whole "
                    "distance is local routing."
                )
            )
        else:
            summary = (
                f"How your {total_ms:.0f} ms builds: measured live from the "
                "game; intermediate routers beyond the visible hops do not "
                "answer probes."
            )
    return {"segments": segs, "summary": summary, "inside_ms": inside_ms,
            "outside_ms": outside_ms, "biggest_jump_ms": max(
                [s["slice_ms"] for s in segs] or [0.0]
            )}


def comparison_verdict(comparison: dict) -> str:
    """Single-line verdict like '12ms better · 3 fewer hops'."""
    imp = comparison.get("latency_improvement", 0)
    hops = comparison.get("public_hops", 0) - comparison.get("optimized_hops", 0)
    jit = comparison.get("jitter_improvement", 0)
    parts = []
    if imp > 0:
        parts.append(f"{imp:.0f} ms lower")
    elif imp < 0:
        parts.append(f"{abs(imp):.0f} ms higher")
    else:
        parts.append("no latency change")
    if hops != 0:
        parts.append(f"{abs(hops)} fewer hops" if hops > 0 else f"{abs(hops)} more hops")
    if abs(jit) >= 1:
        parts.append(f"{abs(jit):.1f} ms {'less' if jit >= 0 else 'more'} jitter")
    return " · ".join(parts) if parts else "routing equality"