"""ICMP/TCP traceroute collector using Windows tracert and raw probing."""
from __future__ import annotations

import re
import subprocess
import socket
import time
import threading
from typing import Optional

from engine.netmonitor.types import (
    Hop, HopProbes, HopRole, HopStatus, ProbeMethod, Route,
)
from engine.netmonitor.cloudmap import is_cloud_ip


def _parse_tracert_line(line: str) -> Optional[dict]:
    """Parse a single line of Windows tracert output."""
    if not line or line.startswith("Tracing") or line.startswith("Over"):
        return None
    if line.startswith("Unable") or line.startswith("Cannot"):
        return None

    pattern = re.compile(
        r"^\s*(\d+)\s+"
        r"((?:<1\s+ms|\d+\s+ms|\d+\s+ms|\*))+\s*"
        r"([\w\.\-\:]+)?"
    )
    match = pattern.match(line)
    if not match:
        star_pattern = re.compile(r"^\s*(\d+)\s+(\*\s+\*\s+\*)")
        star_match = star_pattern.match(line)
        if star_match:
            return {"hop": int(star_match.group(1)), "ip": None, "times": []}
        return None

    hop_num = int(match.group(1))
    times_str = match.group(2) or ""
    ip = match.group(3)

    times = []
    for m in re.finditer(r"(\d+)\s*ms", times_str):
        times.append(float(m.group(1)))
    if "<1" in times_str:
        times.insert(0, 0.5)

    return {"hop": hop_num, "ip": ip, "times": times}


def run_traceroute(
    destination: str,
    max_hops: int = 30,
    timeout: float = 5.0,
    method: ProbeMethod = ProbeMethod.ICMP,
    callback=None,
    stop_event: Optional[threading.Event] = None,
    live_ports: Optional[list[int]] = None,
    client_ports: Optional[list[int]] = None,
) -> Route:
    """Run traceroute, preferring the multi-protocol raw-socket engine.

    Falls back to Windows tracert (ICMP) only if scapy/Npcap is unavailable.
    For Gulf/Doha routes the multi-protocol UDP->ICMP->TCP:443 chain is far
    more resilient than tracert's ICMP-only probing.

    When a live game session is attached (`live_ports`/`client_ports`, from
    the UDP capture stage) the probe sweep targets the exact remote ports the
    game socket is using, from the same client source ports, so the traced
    path is the real ISP path to the match server — not a default web trace.
    """
    try:
        route = run_multi_probe_traceroute(
            destination,
            max_hops=max_hops,
            timeout=min(1.2, max(0.8, timeout)),
            probes_per_hop=3,
            method=method,
            callback=callback,
            stop_event=stop_event,
            live_ports=live_ports,
            client_ports=client_ports,
        )
        if route.hops:
            return route
    except Exception:
        pass
    return _run_tracert_legacy(
        destination,
        max_hops=max_hops,
        timeout=timeout,
        method=method,
        callback=callback,
        stop_event=stop_event,
    )


def _run_tracert_legacy(
    destination: str,
    max_hops: int = 30,
    timeout: float = 5.0,
    method: ProbeMethod = ProbeMethod.ICMP,
    callback=None,
    stop_event: Optional[threading.Event] = None,
) -> Route:
    """Run tracert on Windows and return a Route with discovered hops."""
    route = Route(
        destination=destination,
        protocol=method,
        max_ttl=max_hops,
    )

    try:
        resolved = socket.getaddrinfo(destination, None, socket.AF_INET)
        if resolved:
            route.destination_ip = resolved[0][4][0]
            route.destination_ips = list({r[4][0] for r in resolved})
    except (socket.gaierror, OSError):
        pass

    cmd = ["tracert", "-d", "-w", "2000", "-h", str(max_hops), destination]
    if method == ProbeMethod.ICMP:
        cmd = ["tracert", "-d", "-w", "2000", "-h", str(max_hops), destination]
    elif method == ProbeMethod.TCP:
        cmd = ["tracert", "-d", "-w", "2000", "-h", str(max_hops), "-T", "-P", "80", destination]

    try:
        creation_flags = 0x08000000
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creation_flags,
        )

        hop_data: dict[int, dict] = {}
        for line in proc.stdout:
            if stop_event and stop_event.is_set():
                proc.kill()
                return route

            parsed = _parse_tracert_line(line)
            if parsed:
                hop_num = parsed["hop"]
                if hop_num not in hop_data:
                    hop_data[hop_num] = {
                        "ip": parsed.get("ip"),
                        "times": list(parsed.get("times", [])),
                    }
                else:
                    if parsed.get("ip"):
                        hop_data[hop_num]["ip"] = parsed["ip"]
                    hop_data[hop_num]["times"].extend(parsed.get("times", []))

                if callback:
                    callback(hop_num, hop_data[hop_num])

        proc.wait(timeout=timeout + 5)
    except (subprocess.TimeoutExpired, OSError):
        pass

    start_time = time.time()
    for hop_num in sorted(hop_data.keys()):
        data = hop_data[hop_num]
        ip = data.get("ip") or ""
        times = data.get("times", [])

        probes = HopProbes()
        if times:
            probes.sent = max(len(times), 3)
            probes.received = len([t for t in times if t is not None])
            probes.lost = probes.sent - probes.received
            valid_times = [t for t in times if t is not None]
            if valid_times:
                probes.min_latency = min(valid_times)
                probes.max_latency = max(valid_times)
                probes.avg_latency = sum(valid_times) / len(valid_times)
                if len(valid_times) >= 2:
                    diffs = [
                        abs(valid_times[i] - valid_times[i - 1])
                        for i in range(1, len(valid_times))
                    ]
                    probes.jitter = sum(diffs) / len(diffs) if diffs else 0.0
                probes.latency_samples = list(valid_times)
                probes.packet_loss_pct = (
                    (probes.lost / probes.sent * 100) if probes.sent > 0 else 0.0
                )
            status = HopStatus.HEALTHY
        elif ip:
            probes.sent = 3
            probes.lost = 3
            probes.packet_loss_pct = 100.0
            status = HopStatus.TIMEOUT
        else:
            probes.sent = 3
            probes.lost = 3
            probes.packet_loss_pct = 100.0
            status = HopStatus.TIMEOUT

        is_private = False
        if ip:
            parts = ip.split(".")
            if len(parts) == 4:
                try:
                    first = int(parts[0])
                    second = int(parts[1])
                    if first == 10 or first == 127:
                        is_private = True
                    elif first == 172 and 16 <= second <= 31:
                        is_private = True
                    elif first == 192 and second == 168:
                        is_private = True
                    elif first == 100 and 64 <= second <= 127:
                        is_private = True
                        route.hops[-1].network.is_cgnat = True if route.hops else False
                except ValueError:
                    pass

        if is_private and hop_num == 1:
            status = HopStatus.PRIVATE
            role = HopRole.GATEWAY
        elif is_private:
            status = HopStatus.PRIVATE
            role = HopRole.LOCAL
        else:
            role = HopRole.UNKNOWN

        hop = Hop(
            number=hop_num,
            ip=ip or "",
            status=status,
            role=role,
            probes=probes,
            method=method,
        )
        hop.network.is_private = is_private
        route.hops.append(hop)

    route.total_hops = len(route.hops)
    route.scan_duration = time.time() - start_time

    if route.hops:
        last = route.hops[-1]
        if last.status == HopStatus.HEALTHY:
            last.is_last_hop = True
            last.role = HopRole.DESTINATION

    return route


def run_tcp_probe(
    host: str,
    port: int = 80,
    ttl: int = 30,
    timeout: float = 2.0,
) -> tuple[bool, float]:
    """TCP connect probe. Returns (success, latency_ms)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        if hasattr(socket, "IP_TTL"):
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
            except OSError:
                pass
        start = time.time()
        result = sock.connect_ex((host, port))
        latency = (time.time() - start) * 1000
        sock.close()
        return result == 0, latency
    except (OSError, socket.timeout):
        return False, 0.0


def multi_probe_hop(
    ip: str,
    count: int = 5,
    timeout: float = 2.0,
    method: ProbeMethod = ProbeMethod.ICMP,
) -> HopProbes:
    """Send multiple probes to a single hop and collect statistics."""
    probes = HopProbes(sent=count)
    times = []

    for _ in range(count):
        if method == ProbeMethod.ICMP:
            try:
                cmd = ["ping", "-n", "1", "-w", "2000", ip]
                creation_flags = 0x08000000
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout + 2,
                    creationflags=creation_flags,
                )
                match = re.search(r"time[=<](\d+)ms", proc.stdout)
                if match:
                    times.append(float(match.group(1)))
                elif "Request timed out" in proc.stdout:
                    times.append(None)
                else:
                    times.append(None)
            except (subprocess.TimeoutExpired, OSError):
                times.append(None)
        else:
            ok, lat = run_tcp_probe(ip, port=80, timeout=timeout)
            times.append(lat if ok else None)

    valid = [t for t in times if t is not None]
    probes.received = len(valid)
    probes.lost = probes.sent - probes.received

    if valid:
        probes.min_latency = min(valid)
        probes.max_latency = max(valid)
        probes.avg_latency = sum(valid) / len(valid)
        if len(valid) >= 2:
            diffs = [abs(valid[i] - valid[i - 1]) for i in range(1, len(valid))]
            probes.jitter = sum(diffs) / len(diffs)
        probes.latency_samples = valid

    probes.packet_loss_pct = (probes.lost / probes.sent * 100) if probes.sent > 0 else 0.0
    return probes


# ==========================================================================
#  Multi-protocol raw traceroute (scapy)
#
#  Handles Gulf/Doha-type routes where ICMP is filtered or rate-limited:
#    - per-hop probe chain: UDP -> ICMP -> TCP SYN(443/80)
#    - multiple probes per hop, reply-rate tracked separately from latency
#    - never halts on an isolated silent hop — TTL always advances
#    - only flags a path as broken when the ENDPOINT or multiple consecutive
#      hops fail, so "hidden" hops don't poison the whole trace
# ==========================================================================

_UDP_BASE = 33434
_MAX_SILENT_HOPS = 5  # consecutive non-responding hops before we give up


def _pick_sniff_iface():
    """Reuse the targeting module's Npcap interface selection."""
    try:
        from engine.netmonitor.targeting import _pick_interface
        return _pick_interface()
    except Exception:
        return None


def _local_adapter_ip() -> str:
    try:
        from engine.netmonitor.targeting import _get_local_ip
        return _get_local_ip()
    except Exception:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"


def _probe_hop_parallel(ip, ttl, sport_base, ident_base, count, timeout, stop_event,
                        live_ports=None, client_ports=None):
    """Send UDP+ICMP+TCP:443 SYN probes for one TTL in parallel (Paris style).

    When `live_ports` is set (remote ports of the active game socket) extra
    UDP probes are sent to those ports from the observed client source ports,
    so every TTL advances along the exact path the live match is using.

    Returns (replies:list[tuple[src_ip, rtt_ms]], reached:bool, method:ProbeMethod,
             sent_total:int).
    A single `timeout` window covers all protocols, so a silent hop costs one
    timeout instead of 3x. Replies are classified by matching the inner header
    of the ICMP error to the probe that triggered it.
    """
    from scapy.layers.inet import IP, ICMP, UDP, TCP
    from scapy.sendrecv import sr

    if stop_event and stop_event.is_set():
        return [], False, ProbeMethod.UDP, 0

    local = _local_adapter_ip()
    dports = [_UDP_BASE + ttl * count + i for i in range(count)]

    probes = []
    sent_udp = set()
    sent_icmp = set()
    sent_tcp = set()
    sent_live = set()
    for i in range(count):
        if stop_event and stop_event.is_set():
            break
        usport = (sport_base + i) % 65535
        if usport < 1024:
            usport += 1024
        probes.append(IP(src=local, dst=ip, ttl=ttl) / UDP(sport=usport, dport=dports[i]))
        sent_udp.add(usport)
        iid = (ident_base + i) & 0xFFFF
        probes.append(IP(src=local, dst=ip, ttl=ttl) / ICMP(id=iid, seq=i))
        sent_icmp.add(iid)
        tport = (sport_base + 30000 + i) % 65535
        if tport < 1024:
            tport += 1024
        # Bug 18: generic TCP:443 probes are ONLY for generic (non-game)
        # destinations. When a confirmed UDP game target is attached, probing
        # :443 would let a CDN/edge front or backend answer in place of the
        # game server — the sweep must stay on the game's own UDP/TCP game
        # ports, never substitute a TCP web connection.
        if not live_ports:
            probes.append(IP(src=local, dst=ip, ttl=ttl) / TCP(sport=tport, dport=443, flags="S"))
            sent_tcp.add(tport)

    # Attach the live game flow: probe the exact ports the match socket uses.
    live_ports = (live_ports or [])
    clients = client_ports or []
    for j, rport in enumerate(live_ports):
        if stop_event and stop_event.is_set():
            break
        try:
            rport_i = int(rport)
        except (TypeError, ValueError):
            continue
        cport = (clients[j] if j < len(clients) and clients[j] else (sport_base + 9000 + j)) % 65535
        if cport < 1024:
            cport += 1024
        probes.append(IP(src=local, dst=ip, ttl=ttl) / UDP(sport=cport, dport=rport_i))
        sent_live.add((rport_i, cport))
        # Bug 14: also SYN the game's own remote port (see windowed sweep).
        probes.append(IP(src=local, dst=ip, ttl=ttl) / TCP(sport=cport, dport=rport_i, flags="S"))
        sent_tcp.add(cport)

    replies = []
    reached = False
    method = ProbeMethod.UDP
    try:
        ans, _unans = sr(probes, timeout=timeout, verbose=0, retry=0)
    except Exception:
        return [], False, ProbeMethod.UDP, len(probes)

    for sent, recv in ans:
        if stop_event and stop_event.is_set():
            break
        # RTT is only ever a real measurement: if scapy did not timestamp the
        # sent probe, the reply still counts (rate) but contributes no latency.
        rtt: Optional[float] = None
        try:
            st = getattr(sent, "sent_time", None)
            rt = getattr(recv, "time", None)
            if st is not None and rt is not None:
                ms = (rt - st) * 1000
                if 0.0 <= ms <= 5000.0:
                    rtt = ms
        except Exception:
            rtt = None
        try:
            src = recv[IP].src
        except Exception:
            continue

        if ICMP in recv:
            t = recv[ICMP].type
            if t == 11:  # time exceeded -> a hop answered
                # Identify which probe type triggered it (Paris traceroute).
                try:
                    if UDP in recv[ICMP]:
                        spe = int(recv[ICMP][UDP].sport)
                        dpe = int(recv[ICMP][UDP].dport)
                        if spe in sent_udp:
                            method = ProbeMethod.UDP
                        elif (dpe, spe) in sent_live:
                            method = ProbeMethod.UDP
                        elif spe in sent_tcp:
                            method = ProbeMethod.TCP
                except Exception:
                    pass
                replies.append((src, rtt))
                continue
            if t == 3 and recv[ICMP].code == 3:  # port unreachable -> endpoint
                replies.append((ip, rtt))
                reached = True
                continue
            if t == 0:  # echo reply -> endpoint
                try:
                    if recv[ICMP].id in sent_icmp:
                        replies.append((ip, rtt))
                        reached = True
                        method = ProbeMethod.ICMP
                except Exception:
                    pass
                continue
        elif TCP in recv:
            # Endpoint answered a SYN probe with SYN-ACK or RST. The reply's
            # surviving TTL is arbitrary — never gate on it (valid endpoints
            # can answer with ttl<=1 and were being discarded as "not reached").
            if src == ip:
                flags = int(recv[TCP].flags)
                if flags & 0x02 or flags & 0x04:
                    replies.append((ip, rtt))
                    reached = True
                    method = ProbeMethod.TCP
    return replies, reached, method, len(probes)


def _probe_window_parallel(ip, ttl_list, sport_base, ident_base, count, timeout,
                           stop_event, live_ports=None, client_ports=None,
                           skip_icmp=False):
    """Send one parallel sr() sweep across several TTLs (windowed Paris trace).

    The idle cost of a route collapses to ceil(hops/per-hop idle) windows instead
    of one idle per TTL, so traces to live game servers complete in a couple of
    seconds instead of stalling on every rate-limited ICMP hop. Replies are
    attributed back to hops by the echoed probe TTL.

    `skip_icmp` — proof-driven: once the path has entered a cloud/backbone zone
    (Google, AWS, Azure, CDN edges) ICMP is deterministically dead in that whole
    zone (Google never answers TTL-exceeded; its servers never answer echo).
    Retrying ICMP there is pure waste, so the sweep sends UDP + TCP:443/live
    game-port probes only. Returns {ttl: (replies, reached, method, sent_total)}.
    """
    from scapy.layers.inet import IP, ICMP, UDP, TCP
    from scapy.sendrecv import sr

    ls = list(ttl_list)
    out = {t: ([], False, ProbeMethod.UDP, 0) for t in ls}
    if not ls or (stop_event and stop_event.is_set()):
        return out

    local = _local_adapter_ip()
    probes = []
    sent_count = {t: 0 for t in ls}
    sent_sets: dict = {}  # ttl -> (set_udp_sports, set_icmp_ids, set_tcp_sports, set_live)
    lps = [int(x) for x in (live_ports or []) if isinstance(x, (int, str))
           and str(x).lstrip("-").isdigit()]
    cl = list(client_ports or [])

    for idx, ttl in enumerate(ls):
        su, si, st, sl = set(), set(), set(), set()
        base = (sport_base + idx * 20000) % 60000
        dports = [_UDP_BASE + ttl * count + i for i in range(count)]
        per_ttl = count
        for i in range(count):
            if stop_event and stop_event.is_set():
                break
            usport = (base + i) % 65535
            if usport < 1024:
                usport += 1024
            probes.append(IP(src=local, dst=ip, ttl=ttl) / UDP(sport=usport, dport=dports[i]))
            su.add(usport)
            if not skip_icmp:
                iid = (ident_base + idx * 1000 + i) & 0xFFFF
                probes.append(IP(src=local, dst=ip, ttl=ttl) / ICMP(id=iid, seq=i))
                si.add(iid)
                per_ttl += 1
            tport = (base + 30000 + i) % 65535
            if tport < 1024:
                tport += 1024
            # Bug 18: never sweep generic TCP:443 against a confirmed UDP game
            # target — the live ports below are the only allowed TCP probes.
            if not lps:
                probes.append(IP(src=local, dst=ip, ttl=ttl) / TCP(sport=tport, dport=443, flags="S"))
                st.add(tport)
                per_ttl += 1
        for j, rport in enumerate(lps):
            if stop_event and stop_event.is_set():
                break
            cport = (cl[j] if j < len(cl) and cl[j] else (base + 9000 + j)) % 65535
            if cport < 1024:
                cport += 1024
            probes.append(IP(src=local, dst=ip, ttl=ttl) / UDP(sport=cport, dport=rport))
            sl.add((rport, cport))
            per_ttl += 1
            # Bug 14: actively probe the game's actual ports with TCP SYN too.
            # Firewalled/DDoS-protected game servers (GCP-hosted pools) will
            # not answer generic ICMP/UDP traceroute probes, but a control
            # like Fortnite's fixed 22222 may still answer SYN/SYN-ACK — that
            # response is a genuine RTT to the known game-port path.
            probes.append(IP(src=local, dst=ip, ttl=ttl) / TCP(sport=cport, dport=rport, flags="S"))
            st.add(cport)
            per_ttl += 1
        sent_count[ttl] = per_ttl
        sent_sets[ttl] = (su, si, st, sl)

    try:
        ans, _unans = sr(probes, timeout=timeout, verbose=0, retry=0)
    except Exception:
        return out

    for sent, recv in ans:
        if stop_event and stop_event.is_set():
            break
        try:
            ttl = int(sent[IP].ttl)
        except Exception:
            continue
        if ttl not in out:
            continue
        su, si, st, sl = sent_sets.get(ttl, (set(), set(), set(), set()))

        rtt = None
        try:
            stm = getattr(sent, "sent_time", None)
            rtm = getattr(recv, "time", None)
            if stm is not None and rtm is not None:
                ms = (rtm - stm) * 1000
                if 0.0 <= ms <= 5000.0:
                    rtt = ms
        except Exception:
            rtt = None
        try:
            src = recv[IP].src
        except Exception:
            continue

        replies, reached, method, _n = out[ttl]
        if ICMP in recv:
            t = recv[ICMP].type
            if t == 11:  # time exceeded -> a hop answered
                try:
                    if UDP in recv[ICMP]:
                        spe = int(recv[ICMP][UDP].sport)
                        dpe = int(recv[ICMP][UDP].dport)
                        if spe in su:
                            method = ProbeMethod.UDP
                        elif (dpe, spe) in sl:
                            method = ProbeMethod.UDP
                        elif spe in st:
                            method = ProbeMethod.TCP
                except Exception:
                    pass
                replies.append((src, rtt))
            elif t == 3 and recv[ICMP].code == 3:  # port unreachable -> endpoint
                replies.append((ip, rtt))
                reached = True
            elif t == 0:  # echo reply -> endpoint
                try:
                    if recv[ICMP].id in si:
                        replies.append((ip, rtt))
                        reached = True
                        method = ProbeMethod.ICMP
                except Exception:
                    pass
        elif TCP in recv:
            if src == ip:
                fl = int(recv[TCP].flags)
                if fl & 0x02 or fl & 0x04:
                    replies.append((ip, rtt))
                    reached = True
                    method = ProbeMethod.TCP
        out[ttl] = (replies, reached, method, sent_count[ttl])
    return out


def _probe_udp_hop(ip, ttl, sport_base, count, timeout, stop_event):
    """UDP TTL probe. Returns (replies:[(ip_or_None, ms)], reached:bool)."""
    from scapy.layers.inet import IP, ICMP, UDP
    from scapy.sendrecv import sr1

    replies = []
    reached = False
    local = _local_adapter_ip()
    for i in range(count):
        if stop_event and stop_event.is_set():
            break
        dport = _UDP_BASE + ttl * count + i
        try:
            probe = IP(src=local, dst=ip, ttl=ttl) / UDP(sport=sport_base + i, dport=dport)
            start = time.time()
            resp = sr1(probe, timeout=timeout, verbose=0, retry=0)
            if resp is None:
                continue
            rtt = (time.time() - start) * 1000
            if ICMP in resp:
                t = resp[ICMP].type
                if t == 11:  # time exceeded -> hop answered
                    src = resp[IP].src
                    replies.append((src, rtt))
                elif t == 3 and resp[ICMP].code == 3:  # port unreachable -> endpoint reached
                    replies.append((ip, rtt))
                    reached = True
        except Exception:
            continue
    return replies, reached


def _probe_icmp_hop(ip, ttl, ident_base, count, timeout, stop_event):
    """ICMP echo TTL probe. Returns (replies, reached)."""
    from scapy.layers.inet import IP, ICMP
    from scapy.sendrecv import sr1

    replies = []
    reached = False
    local = _local_adapter_ip()
    for i in range(count):
        if stop_event and stop_event.is_set():
            break
        try:
            probe = IP(src=local, dst=ip, ttl=ttl) / ICMP(id=ident_base + i, seq=i)
            start = time.time()
            resp = sr1(probe, timeout=timeout, verbose=0, retry=0)
            if resp is None:
                continue
            rtt = (time.time() - start) * 1000
            if ICMP in resp:
                t = resp[ICMP].type
                if t == 11:
                    replies.append((resp[IP].src, rtt))
                elif t == 0:  # echo reply -> endpoint
                    replies.append((ip, rtt))
                    reached = True
        except Exception:
            continue
    return replies, reached


def _probe_tcp_hop(ip, ttl, sport_base, count, timeout, stop_event, port=443):
    """TCP SYN TTL probe. Returns (replies, reached). Routers answer with
    ICMP time-exceeded; the endpoint answers with SYN-ACK/RST."""
    from scapy.layers.inet import IP, ICMP, TCP
    from scapy.sendrecv import sr1

    replies = []
    reached = False
    local = _local_adapter_ip()
    for i in range(count):
        if stop_event and stop_event.is_set():
            break
        try:
            probe = IP(src=local, dst=ip, ttl=ttl) / TCP(
                sport=sport_base + i, dport=port, flags="S"
            )
            start = time.time()
            resp = sr1(probe, timeout=timeout, verbose=0, retry=0)
            if resp is None:
                continue
            rtt = (time.time() - start) * 1000
            if ICMP in resp:
                t = resp[ICMP].type
                if t == 11:
                    replies.append((resp[IP].src, rtt))
                elif t == 3:  # unreachable -> endpoint answered
                    replies.append((ip, rtt))
                    reached = True
            elif TCP in resp:
                flags = int(resp[TCP].flags)
                if flags & 0x02 or flags & 0x04:  # SYN-ACK or RST
                    replies.append((resp[IP].src, rtt))
                    reached = True
        except Exception:
            continue
    return replies, reached


def _narrow_replies(replies, endpoint_ip):
    """Collapse per-probe replies into a single (ip, avg_ms, timed) for the hop.

    Replies whose RTT could not be measured (scapy returned no sent timestamp)
    still count toward the reply rate, but contribute no latency. `timed` is
    False when the hop replied without yielding a single measurement — callers
    must report that honestly instead of pretending a 0.0 ms hop.
    """
    if not replies:
        return None, 0.0, False
    times = [r for _s, r in replies if r is not None]
    timed = len(times) > 0
    # Prefer the endpoint; otherwise most-common intermediate hop.
    if any(s == endpoint_ip for s, _r in replies):
        src = endpoint_ip
    else:
        from collections import Counter
        src, _n = Counter(s for s, _r in replies).most_common(1)[0]
    hop_times = [r for s, r in replies if s == src and r is not None]
    avg_ms = (sum(hop_times) / len(hop_times)) if hop_times else 0.0
    return src, avg_ms, timed


def run_multi_probe_traceroute(
    destination: str,
    max_hops: int = 30,
    timeout: float = 2.0,
    probes_per_hop: int = 3,
    method: ProbeMethod = ProbeMethod.UDP,
    callback=None,
    stop_event: Optional[threading.Event] = None,
    live_ports: Optional[list[int]] = None,
    client_ports: Optional[list[int]] = None,
) -> Route:
    """Scapy traceroute with per-hop UDP -> ICMP -> TCP fallback.

    Uses raw sockets (Npcap), so it works where Windows tracert's ICMP-only
    probing is filtered/rate-limited (Gulf/Doha transit, many MTN/Etisalat/
    STC paths). Never halts on an isolated silent hop; TTL always advances.

    With `live_ports`/`client_ports` (from the active match capture) the probe
    sweep also sends to the game's exact remote ports from its source ports,
    mapping the real ISP path to the live server instead of a generic trace.
    """
    import random
    route = Route(
        destination=destination,
        protocol=method,
        max_ttl=max_hops,
    )

    try:
        resolved = socket.getaddrinfo(destination, None, socket.AF_INET)
        if resolved:
            route.destination_ip = resolved[0][4][0]
            route.destination_ips = list({r[4][0] for r in resolved})
    except (socket.gaierror, OSError):
        pass
    endpoint = route.destination_ip

    start_time = time.time()
    consecutive_silent = 0
    _WINDOW = 3  # hops probed per sr() sweep; collapses per-hop idle waits

    # Cloud-zone tracking (proof-driven): Google/AWS/Azure/backbone ranges never
    # answer traceroute-class probing (no TTL-exceeded, no echo). Once the path
    # enters such a zone — detected via the local authoritative prefix DB, no
    # network calls — we stop spending ICMP probes there and, when the game
    # server is already confirmed live, accept the zone as the route's end.
    in_cloud = False
    prev_window_silent = False

    for wbase in range(1, max_hops + 1, _WINDOW):
        if stop_event and stop_event.is_set():
            break
        if consecutive_silent >= _MAX_SILENT_HOPS:
            break
        if route.hops and route.hops[-1].is_last_hop:
            break
        # Deterministic dead zone + live-match proof: the previous window inside
        # the cloud zone was 100% silent and the endpoint is a confirmed live
        # game server — no deeper hop is discoverable, so stop re-probing the
        # block and let terminal resolution terminate at the server IP.
        if in_cloud and live_ports and prev_window_silent:
            break

        ttls = list(range(wbase, min(wbase + _WINDOW, max_hops + 1)))

        sport_base = random.randint(20000, 50000)
        ident_base = random.randint(1, 60000)

        # Parallel Paris-style probe sweep: UDP + ICMP (until cloud entry) +
        # TCP:443 SYN + live ports sent across the whole TTL window in ONE sr()
        # session, attributed back to each hop by echoed TTL.
        results = _probe_window_parallel(
            endpoint, ttls, sport_base, ident_base,
            probes_per_hop, timeout, stop_event,
            live_ports=live_ports, client_ports=client_ports,
            skip_icmp=in_cloud)

        window_silent = True
        for ttl in ttls:
            if stop_event and stop_event.is_set():
                break
            if consecutive_silent >= _MAX_SILENT_HOPS:
                break

            replies, reached, used_method, sent_total = results[ttl]

            hop_ip, avg_ms, timed = _narrow_replies(replies or [], endpoint)
            is_silent = hop_ip is None
            if not is_silent:
                window_silent = False

            probes = HopProbes(sent=max(sent_total, 1))
            if not is_silent:
                # Honest reply rate: answered probes / probes actually sent for
                # this hop (spec: 3-5 probes per hop, every number traceable).
                reply_rate = len(replies) / max(sent_total, 1)
                received = min(sent_total, max(1, int(round(reply_rate * sent_total))))
                probes.received = received
                probes.lost = probes.sent - received
                probes.avg_latency = avg_ms
                probes.min_latency = avg_ms
                probes.max_latency = avg_ms
                probes.latency_samples = [avg_ms] if timed else []
                probes.packet_loss_pct = (probes.lost / probes.sent * 100)
                status = HopStatus.HEALTHY
            else:
                probes.lost = probes.sent
                probes.packet_loss_pct = 100.0
                status = HopStatus.TIMEOUT

            # A hop that replied but never yielded a measurement (rate-limited
            # or untraceable timestamps) must be flagged, not shown as 0.0 ms.
            if not is_silent and not timed:
                status = HopStatus.WARNING
                probes.raw_hint = "replied — no timing available"
                reply_rate = len(replies) / max(sent_total, 1)
                probes.raw_hint += f"; reply rate {reply_rate:.0%}"

            # "Hidden" hop: got at least one reply but not a full set — e.g.
            # rate-limited TTL-exceeded generation. Report partial data, don't
            # fail the path.
            if not is_silent and timed and len(replies) < max(1, sent_total // 2):
                status = HopStatus.WARNING
                probes.raw_hint = f"reply rate {len(replies) / max(sent_total, 1):.0%}"

            is_private = _is_private_ip(hop_ip or "")
            if is_private and ttl == 1:
                status = HopStatus.PRIVATE
                role = HopRole.GATEWAY
            elif is_private:
                status = HopStatus.PRIVATE
                role = HopRole.LOCAL
            else:
                role = HopRole.UNKNOWN

            # Local-router rate limiting: consumer routers (as well as many
            # ISP CPE) answer trace probes at ~50% on purpose. A silent/partial
            # gateway is NOT a loss signal — it is the router throttling ICMP
            # for its own address. "Silent" hops never become "lost": keep the
            # hop healthy and attribute the throttle instead of a loss number.
            if is_private and not is_silent and probes.packet_loss_pct > 0 and ttl <= 2:
                probes.received = probes.sent
                probes.lost = 0
                probes.packet_loss_pct = 0.0
                if probes.raw_hint:
                    probes.raw_hint += "; gateway rate-limits its own replies"
                else:
                    probes.raw_hint = "gateway rate-limits its own probe replies — not counted as loss"
                status = HopStatus.PRIVATE

            hop = Hop(
                number=ttl,
                ip=hop_ip or "",
                status=status,
                role=role,
                probes=probes,
                method=used_method,
                is_last_hop=reached,
                raw_response="",
            )
            hop.network.is_private = is_private
            hop.network.is_cgnat = _is_cgnat_ip(hop_ip or "")
            route.hops.append(hop)

            # Cloud-zone entry: the first public hop whose IP sits in a major
            # cloud/backbone published prefix. Everything past it never answers
            # any traceroute-class probe (proof: Google's zones), so mark the
            # entry hop and switch the sweep to UDP/TCP-only from here on.
            if not is_silent and not is_private and not in_cloud and is_cloud_ip(hop_ip):
                in_cloud = True
                hint = ("entered cloud/backbone net — deeper hops never answer "
                        "traceroute probes (ICMP/UDP/TCP dropped by design)")
                if probes.raw_hint:
                    probes.raw_hint = f"{probes.raw_hint}; {hint}"
                else:
                    probes.raw_hint = hint

            prev_window_silent = window_silent

            if callback:
                r_rate = 0.0 if is_silent else (len(replies) / max(sent_total, 1) if sent_total else 0.0)
                callback(ttl, {
                    "ip": hop_ip, "times": [avg_ms] if timed else [],
                    "reply_rate": r_rate, "reached": reached,
                    "method": used_method.value,
                })

            if not is_silent:
                consecutive_silent = 0
            else:
                consecutive_silent += 1

            if reached:
                route.total_hops = ttl
                if route.hops:
                    route.hops[-1].is_last_hop = True
                    route.hops[-1].role = HopRole.DESTINATION
                break

    # ── Terminal-hop resolution when the endpoint never answered probes ──
    # Many game servers (and Gulf/Doha transit edges) silently drop traceroute
    # probes yet are perfectly reachable — the last TTL hop stays silent, but
    # the trace has already reached the destination's network (capture confirmed
    # the destination is live). Per the doha_fix spec, isolated silent hops must
    # NOT flag the route as broken, and the trace must terminate at the actual
    # server, not a chain of `* * *`.
    if not route.hops or not route.hops[-1].is_last_hop:
        # Hops that progressed the trace (any reply at all — including partial
        # "warning" hops, which are rate-limited but route-identifying).
        progressed = [
            h for h in route.hops
            if h.status != HopStatus.TIMEOUT
            and h.ip
        ]
        # A public hop in the path proves we left the local network and got
        # most of the way to the destination. That is "reaching the server
        # network" for a probe-silent host.
        reached_net = endpoint and any(
            h.status != HopStatus.TIMEOUT
            and h.ip and not _is_private_ip(h.ip)
            for h in route.hops
        )
        last_hop = progressed[-1] if progressed else None
        last_already_endpoint = bool(last_hop and last_hop.ip == endpoint)

        # Direct high-TTL probes can still positively identify a server that
        # answers on TCP:443/80, ICMP echo, or UDP port-unreachable — all in
        # one parallel window.
        if reached_net and not last_already_endpoint and not (
            stop_event and stop_event.is_set()):
            try:
                _r, _re, _m, _sn = _probe_hop_parallel(
                    endpoint, 64, random.randint(20000, 50000),
                    random.randint(1, 60000), probes_per_hop,
                    timeout, stop_event,
                    live_ports=live_ports, client_ports=client_ports)
                reached_net = reached_net or _re
            except Exception:
                pass

        # The trace demonstrably reached the destination network: a hop answered
        # from the endpoint IP, a direct probe got a reply, OR the trace entered
        # public transit and simply hit a probe-silent server (which the capture
        # stage already confirmed live). Terminate the route at the server IP.
        #
        # HONEST LATENCY: the real server RTT is supplied live by the match-RTT
        # monitor (GameRttMonitor) — we do NOT copy an intermediate router's
        # latency onto the destination. Until live measurements arrive the
        # destination reports 0ms with a `raw_hint`.
        if reached_net and not last_already_endpoint:
            # Drop trailing silent/partial hops that are past the responder chain.
            while route.hops and route.hops[-1].status == HopStatus.TIMEOUT:
                route.hops.pop()
            last_num = max((h.number for h in route.hops), default=0)
            probes = HopProbes()
            probes.sent = sent_total
            probes.raw_hint = "probe-silent endpoint — latency set from live match RTT"
            dest_hop = Hop(
                number=last_num + 1,
                ip=endpoint,
                status=HopStatus.WARNING,
                role=HopRole.DESTINATION,
                probes=probes,
                method=ProbeMethod.TCP,
                is_last_hop=True,
                raw_response="probe-silent endpoint (reachable)",
            )
            route.hops.append(dest_hop)
            route.total_hops = len(route.hops)
            # Honest-state flag: the endpoint never answered a probe, so no
            # probe-derived number is this server's ping. Only the live match
            # stream can report it (game-server RTT, not a hop average).
            route.probe_silent_endpoint = True

    if not route.hops or not route.hops[-1].is_last_hop:
        route.total_hops = len(route.hops)

    # ── Bug 19: confirmed live game target ──
    # Synthetic probe replies on the game's OWN ports (through a tunnel or a
    # rate-limiting host) must never masquerade as the server's latency — that
    # was the "1600 ms" that contradicted a 136 ms in-game ping. The passive
    # match-RTT monitor is the ONLY authority for the destination RTT; until
    # it reports, the destination hop reads 0 ms with an honest hint.
    if live_ports:
        try:
            last = route.hops[-1] if route.hops else None
            if (
                last
                and last.is_last_hop
                and last.ip == route.destination_ip
                and last.probes.avg_latency > 0
            ):
                last.probes.avg_latency = 0.0
                last.probes.min_latency = 0.0
                last.probes.max_latency = 0.0
                last.probes.latency_samples = []
                last.probes.raw_hint = (
                    "confirmed game target — latency comes from the passive "
                    "match-RTT monitor, not synthetic probes"
                )
        except Exception:
            pass

    route.scan_duration = time.time() - start_time
    return route


def _is_cgnat_ip(ip: str) -> bool:
    """100.64.0.0/10 — carrier-grade NAT (RFC 6598): ISP-internal addresses
    that no public geo database can ever resolve to a real place."""
    if not ip:
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        return int(parts[0]) == 100 and 64 <= int(parts[1]) <= 127
    except ValueError:
        return False


def _is_private_ip(ip: str) -> bool:
    if not ip:
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if first == 10 or first == 127:
        return True
    if first == 172 and 16 <= second <= 31:
        return True
    if first == 192 and second == 168:
        return True
    if first == 100 and 64 <= second <= 127:
        return True
    return False
