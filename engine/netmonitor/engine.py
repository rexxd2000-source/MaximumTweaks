"""Main orchestrator â€” ties all network monitor components together."""
from __future__ import annotations

import threading
import time
from typing import Optional, Callable

from engine.netmonitor.types import (
    Hop, HopStatus, LiveRttStats, MonitorState, ProbeMethod, Route, RouteEvent,
    ViewMode,
)
from engine.netmonitor.traceroute import run_traceroute
from engine.netmonitor.targeting import _diag
from engine.netmonitor.ping import PingMonitor
from engine.netmonitor.resolver import (
    resolve_dns, resolve_hop, classify_hop_role,
    get_local_ip, get_default_gateway, get_dns_resolver,
    tag_anycast, anycast_pin,
)
from engine.netmonitor.physics import enforce_route_physics
from engine.netmonitor.state import RouteStateEngine
from engine.netmonitor.socket_table import find_game_pids, game_socket_state
from engine.netmonitor.health import HealthAnalyzer
from engine.netmonitor.explainer import RouteExplainer


def _enrich_geo(hops: list, anchor) -> None:
    """Provider-region override (curated cloud ranges beat ip-api's DB),
    public/edge range de-geolocation (Bug 3), cloud-ASN approximate flags,
    and per-hop fiber-floor plausibility."""
    try:
        from engine.netmonitor.cloudmap import provider_geo, cloud_hint, cloud_edge_hint
        from engine.netmonitor.physics import validate_hop_geo

        for hop in hops:
            if not hop.ip or hop.network.is_private:
                continue
            org = hop.network.as_org or hop.network.isp
            if hop.geo and not (hop.geo.city or hop.geo.latitude):
                continue
            override = provider_geo(hop.ip, org)
            if override is not None:
                hop.geo = override
            else:
                # Public/peering/edge hop (Google search/edge blocks, CloudFront,
                # Akamai, Meta CDN, DNS anycast, ...): never pin a corporate-HQ
                # city or coordinates — the DB "Mountain View" for 72.14.216.130
                # is the registrant HQ, not the 28 ms endpoint (Bug 3).
                edge = cloud_edge_hint(hop.ip, org)
                if edge:
                    geo = hop.geo
                    if geo is None:
                        from engine.netmonitor.types import HopGeo
                        geo = HopGeo()
                        hop.geo = geo
                    geo.country = ""
                    geo.region = ""
                    geo.city = ""
                    geo.latitude = 0.0
                    geo.longitude = 0.0
                    geo.verified = False
                    geo.approximate = True
                    hop.geo.hint = (
                        edge + " \u2014 database city is provider HQ, "
                        "not the endpoint location"
                    )
                else:
                    hint = cloud_hint(org)
                    if hint and hop.geo and hop.geo.city:
                        hop.geo.approximate = True
                        if not hop.geo.hint:
                            hop.geo.hint = hint
            if hop.geo and anchor is not None:
                try:
                    validate_hop_geo(hop, anchor)
                except Exception:
                    pass
            # Real city from the ISP's own signals, where the DB is too coarse:
            # reverse-DNS PoP codes (cpt/jhb/dbn/pe + world codes like fra/ams),
            # then the static table (user overrides + built-in facts), then the
            # owning RIR's RDAP. Runs per-hop in the scan worker; cached/guarded.
            try:
                from engine.netmonitor.cityres import resolve_hop_city
                resolve_hop_city(hop, allow_rir=True)
            except Exception:
                pass
    except Exception:
        pass


class NetworkMonitorEngine:
    def __init__(self):
        self.state_engine = RouteStateEngine()
        self.health = HealthAnalyzer()
        self.explainer = RouteExplainer()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ping_monitor: Optional[PingMonitor] = None
        self._lock = threading.Lock()
        self._on_route_update: list[Callable] = []
        self._on_event: list[Callable] = []
        self._scan_interval = 30.0
        self.view_mode = ViewMode.BASIC
        self._rtt_monitor: Optional[object] = None
        # Per-destination headline-latency history across scans (Bug 17):
        # feeds Route.hist_lat_range_ms so confidence drops when the number
        # itself swings wildly between traces.
        self._dest_lat_hist: dict[str, list[float]] = {}
        self._live_healthy_ts: float = 0.0
        # Last well-sampled live RTT (held so a thin 1-2 sample median never
        # yanks the headline between probe-avg and a freak value).
        self._live_sticky: Optional[dict] = None
        # OS-tracert ground-truth cross-check (spec Step 2.5): a single
        # `tracert -d` run behind the scans, fed into Route.os_tracert_match.
        self._tracert_started = False
        self._os_tracert_hops: list[str] = []
        # BGP routing-intelligence for the international leg (spec: BGP
        # looking-glass data, honestly labeled as BGP-sourced). Resolved once
        # per session in the background, folded into Route.bgp_path.
        self._bgp_started = False
        self._bgp_isp: Optional[dict] = None
        self._bgp_dest: Optional[dict] = None
        # Throttle the stale-target warning so a dead match doesn't spam.
        self._stale_emit_ts: float = 0.0

    # A live median needs a real sample set before it is authoritative â€”
    # with 1-2 pairs the median is noise and the displayed total toggles.
    _LIVE_MIN_SAMPLES = 8
    # How long a held value stays authoritative after the stream thins out.
    _LIVE_STALE_S = 60.0
    # Match/server rotation lock: after this much silence on the locked server
    # (45s felt like an eternity mid-match), flag the session stale so the UI
    # re-locks the CURRENT server and the SERVER dot stops pinning the old one.
    _ROTATE_STALE_S = 20.0

    @property
    def state(self) -> MonitorState:
        return self.state_engine.state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def on_route_update(self, callback: Callable):
        self._on_route_update.append(callback)

    def on_event(self, callback: Callable):
        self._on_event.append(callback)

    def set_scan_interval(self, seconds: float):
        self._scan_interval = max(10.0, seconds)

    def start_monitoring(self, destination: str, target=None):
        if self.running:
            self.stop()

        self._stop.clear()
        self.state_engine.state.destination = destination
        self.state_engine.state.monitoring = True
        self.state_engine.state.live_stale = False
        self._tracert_started = False

        # Attach the live game session (from UDP capture): the traceroute
        # probes the same remote ports the match socket uses, and a passive
        # RTT monitor keeps the destination latency equal to in-match values.
        self._rtt_monitor = None
        if target is not None and getattr(target, "found", False) and target.ip:
            if target.protocol is not ProbeMethod.UDP:
                # Bug 18 hard guard: never let a non-UDP candidate masquerade
                # as the in-match server. Monitor the destination normally
                # (generic probes) but do NOT attach live ports/RTT, which
                # would bless a TCP/CDN endpoint as the game server.
                self._emit_event(
                    "warning",
                    f"Detection returned non-UDP target {target.ip} — "
                    "ignored as game server (UDP-only signature)",
                )
                target = None
        if target is not None and getattr(target, "found", False) and target.ip:
            self.state_engine.state.live_target_ip = target.ip
            self.state_engine.state.live_remote_ports = list(target.remote_ports or [])
            self.state_engine.state.live_client_ports = list(target.client_ports or [])
            self.state_engine.state.live_target_ports_text = "/".join(
                str(p) for p in (target.remote_ports or [])
            )
            try:
                from engine.netmonitor.targeting import GameRttMonitor, _pick_interface
                self._rtt_monitor = GameRttMonitor(
                    server_ip=target.ip,
                    remote_ports=target.remote_ports or [],
                    on_stats=self._apply_live_rtt,
                    # Reuse the EXACT interface the resolver proved carries the
                    # match traffic (a GetBestInterface guess picks ExitLag's
                    # virtual adapter and sniffs nothing — Bug 19 root cause).
                    iface=getattr(target, "iface", None) or _pick_interface(target.ip),
                )
                self._rtt_monitor.start()
            except Exception:
                self._rtt_monitor = None

        try:
            resolved = resolve_dns(destination)
            self.state_engine.state.dns_info = resolved
            if resolved.ipv4:
                self.state_engine.state.destination_ip = resolved.ipv4[0]
        except Exception:
            pass

        self._emit_event("info", f"Monitoring started: {destination}")
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True
        )
        self._thread.start()

        # Spec Step 2.5 ground truth: one OS tracert behind the scans, matched
        # hop-for-hop against our probe path. Runs once per monitoring session.
        if not self._tracert_started and (
            self.state_engine.state.live_target_ip
            or self.state_engine.state.destination_ip
        ):
            self._tracert_started = True
            threading.Thread(target=self._os_tracert_thread, daemon=True).start()

        # Spec: BGP routing intelligence for the international leg — resolved
        # once per session, folded into Route.bgp_path, honestly labeled.
        if not self._bgp_started:
            self._bgp_started = True
            threading.Thread(target=self._bgp_thread, daemon=True).start()

        self._start_ping(destination)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        if self._rtt_monitor:
            self._rtt_monitor.stop()
            self._rtt_monitor = None
        if self._ping_monitor:
            self._ping_monitor.stop()
            self._ping_monitor = None
        self.state_engine.state.monitoring = False
        self.state_engine.state.live_target_ip = ""
        self.state_engine.state.live_remote_ports = []
        self.state_engine.state.live_client_ports = []
        self.state_engine.state.live_target_ports_text = ""
        self._emit_event("info", "Monitoring stopped")

    def run_single_scan(self, destination: str) -> Route:
        route = self._perform_scan(destination)
        return route

    def resolve_game_server(
        self,
        game: str,
        duration: float = 8.0,
        stop_event=None,
        bypass_relay_filter: bool = False,
    ):
        """Target-resolution pre-step: sniff live UDP traffic, match the
        per-game port signature, and return the real in-game match server
        (TargetMatch). Feed result.ip into start_monitoring() unchanged.
        """
        from engine.netmonitor.targeting import resolve_game_server
        return resolve_game_server(
            game=game,
            duration=duration,
            stop_event=stop_event,
            bypass_relay_filter=bypass_relay_filter,
        )

    def get_state(self) -> MonitorState:
        return self.state_engine.state

    def get_route(self) -> Optional[Route]:
        return self.state_engine.state.active_route

    def get_previous_route(self) -> Optional[Route]:
        return self.state_engine.state.previous_route

    def get_comparison(self):
        return self.state_engine.get_previous_comparison()

    def get_events(self, limit: int = 100) -> list[RouteEvent]:
        return self.state_engine.get_events(limit)

    def get_latency_history(
        self, hop_number: int, window: float = 300
    ) -> list[tuple[float, float]]:
        return self.state_engine.get_latency_history(hop_number, window)

    def get_ping_samples(self) -> list[tuple[float, float]]:
        if self._ping_monitor:
            return self._ping_monitor.get_samples()
        return []

    def get_basic_view(self) -> dict:
        route = self.get_route()
        if not route:
            return {}
        return self.explainer.basic_view(route, self.state_engine.state)

    def get_advanced_view(self) -> dict:
        route = self.get_route()
        if not route:
            return {}
        return self.explainer.advanced_view(route, self.state_engine.state)

    def _monitor_loop(self):
        while not self._stop.is_set():
            try:
                self._perform_scan()
            except Exception as exc:
                self._emit_event("error", f"Scan error: {exc}")
            # Spec Step 3.3: the locked target stopped receiving traffic
            # (match ended / server rotated). Flag it so the UI re-runs the
            # detection pipeline fresh instead of tracing a dead connection.
            try:
                if (
                    self.state_engine.state.has_live_target
                    and time.time() - self._live_healthy_ts > self._ROTATE_STALE_S
                ):
                    self._set_live_stale()
            except Exception:
                pass
            self._stop.wait(self._scan_interval)

    def _set_live_stale(self):
        state = self.state_engine.state
        if state.live_stale:
            return
        state.live_stale = True
        now = time.time()
        if now - self._stale_emit_ts > 30.0:
            self._stale_emit_ts = now
            self._emit_event(
                "warning",
                "No further traffic to the locked server — match ended or "
                "rotated. Re-running fresh live-server detection.",
            )

    def _os_tracert_thread(self):
        """Run Windows tracert -d once in the background and keep the public
        hop sequence as ground truth for spec Step 2.5 cross-validation."""
        dest = (
            self.state_engine.state.live_target_ip
            or self.state_engine.state.destination_ip
            or self.state_engine.state.destination
        )
        if not dest:
            return
        try:
            import subprocess
            from engine.netmonitor.traceroute import _parse_tracert_line

            _diag(f"[tracert] OS cross-check to {dest} (background)")
            start = time.time()
            proc = subprocess.run(
                ["tracert", "-d", "-h", "30", "-w", "300", dest],
                capture_output=True,
                text=True,
                timeout=75,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            hops: list[str] = []
            for line in (proc.stdout or "").splitlines():
                parsed = _parse_tracert_line(line)
                if parsed and parsed.get("ip"):
                    hops.append(parsed["ip"].split(" ")[0])
            self._os_tracert_hops = hops
            _diag(
                f"[tracert] OS resolved {len(hops)} hops in "
                f"{time.time() - start:.0f}s: {' '.join(hops[:12])}"
            )
        except Exception as exc:
            _diag(f"[tracert] OS cross-check failed: {exc!r}")

    def _match_os_tracert(self, route: Route):
        """Fold the OS tracert hop sequence into the route: how many of the
        OS's public hop IPs our probe path also reproduced, in order."""
        os_hops = list(self._os_tracert_hops)
        if not os_hops:
            return
        pub = [h.ip for h in route.hops if h.ip and not h.network.is_private]
        if not pub:
            return
        i = 0
        matched = 0
        for osip in os_hops:
            while i < len(pub) and pub[i] != osip:
                i += 1
            if i < len(pub):
                matched += 1
                i += 1
        ratio = matched / len(os_hops) if os_hops else 0.0
        if len(os_hops) >= 3 and ratio >= 0.8:
            note = (
                f"OS tracert ground-truth: reproduced {matched}/{len(os_hops)} "
                "public hops in order"
            )
        elif matched >= 2 and ratio >= 0.5:
            note = (
                f"OS tracert mostly agrees ({matched}/{len(os_hops)} "
                "public hops in order)"
            )
        elif matched >= 1:
            note = f"Weak OS tracert overlap ({matched}/{len(os_hops)} public hops)"
        else:
            note = "OS tracert path does not reproduce our probes"
        route.os_tracert_match = {
            "os_hops": os_hops,
            "prefix_match": matched,
            "os_count": len(os_hops),
            "note": note,
        }

    def _bgp_thread(self):
        """Resolve BGP routing intelligence once per session (spec: BGP
        looking-glass data for the international leg, honestly labeled).
        Looks up the announcing ASN/name for the destination and for the
        user's first public (SA) hop. Never fabricated: on any failure the
        route simply shows no BGP nodes."""
        try:
            dest = (
                self.state_engine.state.live_target_ip
                or self.state_engine.state.destination_ip
            )
            if dest:
                from engine.netmonitor.bgp import lookup_ipapi, lookup_ipinfo

                asn = name = country = city = prefix = ""
                info = lookup_ipinfo(dest)
                if info:
                    org = info.get("org", "")
                    if org and "AS" in org:
                        try:
                            asn_tok = org.split(" ")[0].replace("AS", "")
                            asn = asn_tok
                            name = org[len(org.split(" ")[0]) + 1:]
                        except (IndexError, ValueError):
                            pass
                    country = info.get("country", "")
                    city = info.get("city", "")
                if not asn:
                    info = lookup_ipapi(dest)
                    if info:
                        as_raw = info.get("as", "")
                        if as_raw and " " in as_raw:
                            asn = as_raw.split(" ")[0].replace("AS", "")
                            name = info.get("asOrganization", "") or ""
                        country = info.get("country", "") or country
                        city = info.get("city", "") or city
                if asn:
                    self._bgp_dest = {
                        "ip": dest, "asn": int(asn), "name": name,
                        "country": country, "city": city,
                        "source": "BGP routing data (ASN registration)",
                    }
                    _diag(
                        f"[bgp] dest {dest} -> AS{asn} {name or ''} "
                        f"({city or ''} {country or ''})"
                    )
        except Exception as exc:
            _diag(f"[bgp] dest lookup failed: {exc!r}")

        try:
            route = self.state_engine.state.active_route
            ip = next(
                (h.ip for h in (route.hops if route else [])
                 if h.ip and not h.network.is_private),
                "",
            )
            if ip and self._bgp_dest:
                from engine.netmonitor.bgp import lookup_ipapi

                info = lookup_ipapi(ip)
                if info:
                    as_raw = info.get("as", "")
                    asn = name = ""
                    if as_raw and " " in as_raw:
                        asn = as_raw.split(" ")[0].replace("AS", "")
                        name = info.get("asOrganization", "") or ""
                    if asn:
                        self._bgp_isp = {
                            "ip": ip, "asn": int(asn), "name": name,
                            "country": info.get("country", ""),
                            "source": "BGP routing data (ASN registration)",
                        }
                        _diag(
                            f"[bgp] isp hop {ip} -> AS{asn} {name or ''}"
                        )
        except Exception as exc:
            _diag(f"[bgp] isp lookup failed: {exc!r}")

    def _fold_bgp_path(self, route: Route):
        """Attach resolved BGP intelligence to the route, or a plain
        'unavailable' marker so the view never fabricates an international
        leg when the lookup failed."""
        if not getattr(self, "_bgp_dest", None) and not getattr(self, "_bgp_isp", None):
            return
        route.bgp_path = {
            "resolved": self._bgp_dest is not None,
            "source": (
                (self._bgp_dest or {}).get("source")
                or "BGP routing data (ASN registration)"
            ),
            "isp": self._bgp_isp,
            "dest": self._bgp_dest,
        }

    def _perform_scan(self, destination: str = None) -> Optional[Route]:
        dest = destination or self.state_engine.state.destination
        if not dest:
            return None

        start_time = time.time()

        def on_hop(num, data):
            pass

        route = run_traceroute(
            dest,
            max_hops=30,
            timeout=5.0,
            callback=on_hop,
            stop_event=self._stop,
            live_ports=self.state_engine.state.live_remote_ports or None,
            client_ports=self.state_engine.state.live_client_ports or None,
        )
        if self.state_engine.state.has_live_target:
            route.rtt_source = "live_game"

        self._emit_event("info", f"Scan completed: {route.total_hops} hops, "
                         f"{route.total_latency:.0f} ms")

        hops_to_resolve = [h for h in route.hops if h.ip and not h.network.is_private]
        resolve_batch_size = 10
        for i in range(0, len(hops_to_resolve), resolve_batch_size):
            if self._stop.is_set():
                break
            batch = hops_to_resolve[i:i + resolve_batch_size]
            for hop in batch:
                if self._stop.is_set():
                    break
                try:
                    hostname, network, geo = resolve_hop(hop.ip)
                    hop.hostname = hostname or hop.hostname
                    hop.network.asn = network.asn or hop.network.asn
                    hop.network.as_org = network.as_org or hop.network.as_org
                    hop.network.isp = network.isp or hop.network.isp
                    hop.network.network_name = network.network_name or hop.network.network_name
                    hop.geo = geo
                    hop.role = classify_hop_role(
                        hop.number,
                        route.total_hops,
                        hop.ip,
                        hop.network,
                        hop.geo,
                        hop.is_last_hop,
                    )
                except Exception:
                    pass

        # â”€â”€ Anycast edge re-anchoring â”€â”€
        # Google/Cloudflare/etc anycast hops report HQ cities (Mountain View).
        # Tag them edge/anycast and pin them to the regional path anchor.
        for hop in route.hops:
            if hop.ip and not hop.network.is_private:
                tag_anycast(hop.network, is_endpoint=hop.is_last_hop)
        for hop in route.hops:
            if hop.ip and not hop.network.is_private:
                try:
                    anycast_pin(hop.network, hop, route)
                except Exception:
                    pass

        # â”€â”€ Cloud-provider region override + per-hop plausibility â”€â”€
        # ip-api's DB mislabels cloud ranges (e.g. a GCP us-west1 pool as
        # "Doha, Qatar"). Curated provider ranges win; other cloud ASNs keep
        # the DB city but are flagged approximate. Every hop with geo+latency
        # is then checked against the fiber floor so a physically impossible
        # label is rejected as unverified instead of trusted.
        try:
            from engine.netmonitor.physics import user_geo_point, validate_dest_geo

            anchor = user_geo_point()
            _enrich_geo(route.hops, anchor)
            validate_dest_geo(route, anchor)
        except Exception:
            pass

        # â”€â”€ Speed-of-light gate â”€â”€
        # Reject physically impossible totals (single-digit ms to a server
        # thousands of km away). Floors are folded in for display.
        try:
            enforce_route_physics(route)
        except Exception:
            pass

        # â”€â”€ Real tunnel re-measurement â”€â”€
        # No static "optimized route" mocks: when an active VPN/GPN tunnel is
        # the OS interface carrying this server, we trace the REAL path through
        # it. Otherwise the optimized side stays absent â€” but the scan itself
        # is always recorded as checked evidence, so the UI never shows a
        # static "no tunnel" claim as if nothing was ever tested.
        if not self._stop.is_set():
            try:
                from engine.netmonitor.tunnel import detect_tunnel

                tunnel = detect_tunnel(route.destination_ip)
                route.tunnel_info = {
                    "name": tunnel.name,
                    "description": tunnel.description,
                    "ipv4": tunnel.ipv4,
                    "kind": tunnel.kind,
                    "routes_server": tunnel.routes_server,
                    "active": tunnel.active,
                    "reason": tunnel.reason,
                    "checked": True,
                }
                if tunnel.active and tunnel.routes_server:
                    tunnel_route = run_traceroute(
                        dest,
                        max_hops=30,
                        timeout=5.0,
                        stop_event=self._stop,
                        live_ports=self.state_engine.state.live_remote_ports or None,
                        client_ports=self.state_engine.state.live_client_ports or None,
                    )
                    if self.state_engine.state.has_live_target:
                        tunnel_route.rtt_source = "live_game"
                    for h in tunnel_route.hops:
                        if h.ip and not h.network.is_private:
                            try:
                                hostname, network, geo = resolve_hop(h.ip)
                                h.hostname = hostname or h.hostname
                                h.network.asn = network.asn or h.network.asn
                                h.network.as_org = network.as_org or h.network.as_org
                                h.network.isp = network.isp or h.network.isp
                                h.network.network_name = network.network_name or h.network.network_name
                                h.geo = geo
                                tag_anycast(h.network, is_endpoint=h.is_last_hop)
                                anycast_pin(h.network, h, tunnel_route)
                            except Exception:
                                pass
                    try:
                        from engine.netmonitor.physics import (
                            user_geo_point, validate_dest_geo,
                        )

                        anchor = user_geo_point()
                        _enrich_geo(tunnel_route.hops, anchor)
                        validate_dest_geo(tunnel_route, anchor)
                        enforce_route_physics(tunnel_route)
                    except Exception:
                        pass
                    route.tunnel_route = tunnel_route
                    route.tunnel_info.update({
                        "routes_server": True,
                        "total_hops": tunnel_route.total_hops,
                        "total_latency": tunnel_route.total_latency,
                    })
                    self._emit_event(
                        "info",
                        f"Tunnel '{tunnel.name}' carries the route â€” "
                        f"re-measured via it ({tunnel_route.total_hops} hops, "
                        f"{tunnel_route.total_latency:.0f} ms)",
                    )
                elif tunnel.active:
                    self._emit_event(
                        "info",
                        f"Active {tunnel.kind} '{tunnel.name}' present but does "
                        f"not carry the route to {route.destination_ip} â€” "
                        f"keeping the direct path",
                    )
                else:
                    self._emit_event(
                        "info",
                        f"Tunnel scan: {tunnel.reason} â€” keeping the direct path",
                    )
            except Exception as exc:
                self._emit_event("warning", f"Tunnel trace failed: {exc}")

        # â”€â”€ Trace-to-trace variance history (Bug 17) â”€â”€
        # Track the headline value per destination across recent scans so
        # confidence reflects stability, not just reply rate. A number that
        # swings 827ms -> 147ms between traces must never read HIGH.
        try:
            key = route.destination_ip or route.destination or "dest"
            vals = self._dest_lat_hist.setdefault(key, [])
            if route.total_latency > 0:
                vals.append(float(route.total_latency))
            vals = vals[-12:]
            self._dest_lat_hist[key] = vals
            route.hist_lat_range_ms = (
                (max(vals) - min(vals)) if len(vals) >= 2 else 0.0
            )
        except Exception:
            route.hist_lat_range_ms = 0.0

        # â”€â”€ OS tracert ground truth (spec Step 2.5) â”€â”€
        try:
            self._match_os_tracert(route)
        except Exception:
            pass

        # BGP routing intelligence for the international leg (spec: BGP
        # looking-glass data, honestly labeled — never fabricated hops).
        try:
            self._fold_bgp_path(route)
        except Exception:
            pass

        changes = self.state_engine.update_route(route)

        if changes:
            for c in changes:
                self._emit_event("warning", c.description)

        for cb in self._on_route_update:
            try:
                cb(route, changes)
            except Exception:
                pass

        return route

    def _apply_live_rtt(self, stats):
        """Fold the passive match-RTT measurement into the active route so
        destination latency mirrors the real-time match metric."""
        with self._lock:
            if stats and getattr(stats, "samples", 0) > 0 and getattr(stats, "median_ms", 0) > 0:
                self._live_healthy_ts = time.time()
                self.state_engine.state.live_stale = False
            # "flow_cadence" is the passive newest-outbound pairing, which
            # converges on the stream's packet period (~25ms for 45/s), NOT the
            # server RTT (measured 142ms via game-port SYN). It only proves the
            # match is alive — never let it feed the sticky/adopt headline.
            if getattr(stats, "source", "") == "flow_cadence":
                return
            route = self.state_engine.state.active_route
            if route is None:
                return

            now = time.time()
            healthy = bool(
                stats and getattr(stats, "samples", 0) > 0
                and getattr(stats, "median_ms", 0) > 0
            )
            if healthy and stats.samples >= self._LIVE_MIN_SAMPLES:
                self._live_sticky = {
                    "median_ms": stats.median_ms,
                    "best_ms": getattr(stats, "best_ms", 0.0),
                    "loss_pct": stats.loss_pct,
                    "samples": stats.samples,
                    "ts": now,
                }

            # Choose the authoritative live value: a WELL-SAMPLED median, or a
            # held one while the match stream is too thin to be believable.
            # Adopting a 1-sample median between scans is exactly what made the
            # destination hop swing 0ms <-> 1162ms on consecutive traces.
            adopt: Optional[LiveRttStats] = None
            if healthy and stats.samples >= self._LIVE_MIN_SAMPLES:
                adopt = stats
            elif (
                self._live_sticky
                and now - self._live_sticky["ts"] < self._LIVE_STALE_S
            ):
                s = self._live_sticky
                adopt = LiveRttStats(
                    source="live_game_traffic",
                    median_ms=s["median_ms"],
                    avg_ms=s["median_ms"],
                    min_ms=s["median_ms"],
                    best_ms=s.get("best_ms", s["median_ms"]),
                    max_ms=s["median_ms"],
                    jitter_ms=0.0,
                    loss_pct=s["loss_pct"],
                    samples=s["samples"],
                    updated=now,
                )
            elif healthy:
                adopt = stats  # nothing better available â€” show what we have

            if adopt is None:
                return

            _diag(
                f"[live_rtt] adopt samples={adopt.samples} "
                f"median={adopt.median_ms:.1f} best={adopt.best_ms:.1f} "
                f"loss={adopt.loss_pct:.1f}%"
            )
            route.live_rtt = adopt
            route.rtt_source = "live_game"
            if route.hops:
                dest = route.hops[-1]
                dest.probes.avg_latency = adopt.median_ms
                dest.probes.min_latency = adopt.min_ms
                dest.probes.max_latency = adopt.max_ms
                dest.probes.jitter = adopt.jitter_ms
                dest.probes.packet_loss_pct = adopt.loss_pct
                dest.probes.raw_hint = "live match RTT (passive insertion)"
                dest.status = (
                    HopStatus.HEALTHY if adopt.loss_pct <= 5 else HopStatus.WARNING
                )
            # Keep the real tunnel re-measurement on the same match metric.
            if route.tunnel_route and route.tunnel_route.hops:
                tr = route.tunnel_route
                tr.live_rtt = stats
                tr.rtt_source = "live_game"
                td = tr.hops[-1]
                td.probes.avg_latency = adopt.median_ms
                td.probes.min_latency = adopt.min_ms
                td.probes.max_latency = adopt.max_ms
                td.probes.jitter = adopt.jitter_ms
                td.probes.packet_loss_pct = adopt.loss_pct
                td.probes.raw_hint = "live match RTT (passive insertion)"
                td.status = (
                    HopStatus.HEALTHY if adopt.loss_pct <= 5 else HopStatus.WARNING
                )

    def _start_ping(self, target: str):
        if self._ping_monitor:
            self._ping_monitor.stop()

        def on_sample(ts, lat):
            pass

        def on_event(evt):
            # Cloud/match servers legitimately filter ICMP: an un-answered
            # icon ping is NOT evidence the game server is down. When the
            # passive match-RTT monitor has recent healthy samples (proven by
            # the game's own packets), suppress ICMP-ping timeouts so the event
            # feed reflects the authoritative signal instead of spamming.
            if evt.level == "warning" and "timeout" in evt.message:
                if time.time() - self._live_healthy_ts < 30:
                    return
            self._emit_event(evt.level, evt.message)

        self._ping_monitor = PingMonitor(
            target=target,
            interval=2.0,
            count=3600,
            on_sample=on_sample,
            on_event=on_event,
        )
        self._ping_monitor.start()

    def _emit_event(self, level: str, message: str):
        evt = RouteEvent(
            timestamp=time.time(),
            level=level,
            message=message,
        )
        self.state_engine.state.events.append(evt)
        for cb in self._on_event:
            try:
                cb(evt)
            except Exception:
                pass

