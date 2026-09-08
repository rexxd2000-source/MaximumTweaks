"""Real city labels for local ISP hops — worldwide.

Generic geo databases are too coarse for regional ISP backbone IPs (they
report a country and often a wrong registered-office city). For a router the
most trustworthy source is the network operator itself:

  1. Reverse-DNS hostnames — ISPs worldwide encode PoP/city codes into router
     hostnames (SA: jhb/cpt/dbn/pe/gqeberha...; world: fra/ams/lon/nyc/sin...).
     This is the single best signal for in-country hops, in any country.
  2. A hand-verified table for specific ISPs: built-in exact-IP facts plus a
     per-user file (%APPDATA%\\MaximumTweaks\\city_overrides.json) so any user
     in any country can correct their own route without a rebuild.
  3. The owning RIR's RDAP allocation records (route via rdap.org to
     RIPE/ARIN/APNIC/LACNIC/AFRINIC) as a low-confidence, cached cross-reference.

When nothing resolves confidently the caller shows the raw IP/hostname
instead of a repeated generic placeholder — an honest "unresolved".
"""
from __future__ import annotations

import ipaddress
import re

# ────────────────────────────────────────────────────────────────────────
# City token -> (city, province) via hostname rDNS. Longest-token-first is
# picked so "johannesburg" wins over "jhb" and "port elizabeth" over "pe".
# ────────────────────────────────────────────────────────────────────────
_SA_CITY_TOKENS: dict[str, tuple[str, str]] = {
    "johannesburg": ("Johannesburg", "Gauteng"),
    "joburg": ("Johannesburg", "Gauteng"),
    "joburgcentral": ("Johannesburg", "Gauteng"),
    "jhb": ("Johannesburg", "Gauteng"),
    "joberg": ("Johannesburg", "Gauteng"),
    "jburg": ("Johannesburg", "Gauteng"),
    "randburg": ("Johannesburg", "Gauteng"),
    "soweto": ("Soweto", "Gauteng"),
    "pretoria": ("Pretoria", "Gauteng"),
    "pty": ("Pretoria", "Gauteng"),
    "centurion": ("Centurion", "Gauteng"),
    "kempton park": ("Kempton Park", "Gauteng"),
    "midrand": ("Midrand", "Gauteng"),
    "cape town": ("Cape Town", "Western Cape"),
    "capetown": ("Cape Town", "Western Cape"),
    "cpt": ("Cape Town", "Western Cape"),
    "stellenbosch": ("Stellenbosch", "Western Cape"),
    "durban": ("Durban", "KwaZulu-Natal"),
    "dbn": ("Durban", "KwaZulu-Natal"),
    "pietermaritzburg": ("Pietermaritzburg", "KwaZulu-Natal"),
    "pmb": ("Pietermaritzburg", "KwaZulu-Natal"),
    "gqeberha": ("Gqeberha", "Eastern Cape"),
    "port elizabeth": ("Gqeberha", "Eastern Cape"),
    "pe": ("Gqeberha", "Eastern Cape"),
    "east london": ("East London", "Eastern Cape"),
    "bloemfontein": ("Bloemfontein", "Free State"),
    "bfn": ("Bloemfontein", "Free State"),
    "kimberley": ("Kimberley", "Northern Cape"),
    "polokwane": ("Polokwane", "Limpopo"),
    "nelspruit": ("Mbombela", "Mpumalanga"),
    "mbombela": ("Mbombela", "Mpumalanga"),
    "richards bay": ("Richards Bay", "KwaZulu-Natal"),
    "rustenburg": ("Rustenburg", "North West"),
    "upington": ("Upington", "Northern Cape"),
}

# Hand-verified coordinates for the cities above (used for map pins only when
# the city was resolved from hostname / the ISP prefix table).
_SA_CITY_COORDS: dict[str, tuple[float, float]] = {
    "Johannesburg": (-26.2041, 28.0473),
    "Soweto": (-26.2678, 27.8585),
    "Pretoria": (-25.7479, 28.2293),
    "Centurion": (-25.8589, 28.1892),
    "Kempton Park": (-26.1115, 28.2361),
    "Midrand": (-25.9895, 28.1285),
    "Cape Town": (-33.9249, 18.4241),
    "Stellenbosch": (-33.9364, 18.8567),
    "Durban": (-29.8587, 31.0218),
    "Pietermaritzburg": (-29.6006, 30.3794),
    "Gqeberha": (-33.9189, 25.6033),
    "East London": (-33.0153, 27.9116),
    "Bloemfontein": (-29.0852, 26.1596),
    "Kimberley": (-28.7282, 24.7499),
    "Polokwane": (-23.8962, 29.4486),
    "Mbombela": (-25.4650, 30.9852),
    "Richards Bay": (-28.7706, 32.0373),
    "Rustenburg": (-25.6167, 27.2000),
    "Upington": (-28.4507, 21.2489),
}


def _city_from_hostname(hostname: str):
    """Best (city, province) from the ISP's own reverse-DNS hostname.

    Tokens are matched space-delimited after normalizing all non-alphanumerics,
    so "pe" can never false-hit "cape"/"peter" — only a standalone "pe".
    SA and world PoP codes are merged; longest-token-first so the most specific
    country's code wins on ambiguity. Returns (city, province, token) or None.
    """
    if not hostname:
        return None
    norm = " " + re.sub(r"[^a-z0-9]+", " ", hostname.lower()).strip() + " "
    for token in sorted(_CITY_TOKENS, key=len, reverse=True):
        if f" {token} " in norm:
            city, province = _CITY_TOKENS[token]
            return city, province, token
    return None


# City -> country for non-SA PoP tokens (SA defaults to "South Africa").
_CITY_COUNTRY: dict[str, str] = {
    "Paris": "France", "Frankfurt": "Germany", "Munich": "Germany",
    "Berlin": "Germany", "Hamburg": "Germany", "Dusseldorf": "Germany",
    "Amsterdam": "Netherlands", "Rotterdam": "Netherlands", "London": "United Kingdom",
    "Manchester": "United Kingdom", "Glasgow": "United Kingdom", "Dublin": "Ireland",
    "Brussels": "Belgium", "Zurich": "Switzerland", "Geneva": "Switzerland",
    "Vienna": "Austria", "Prague": "Czechia", "Warsaw": "Poland",
    "Budapest": "Hungary", "Bucharest": "Romania", "Sofia": "Bulgaria",
    "Istanbul": "Turkey", "Moscow": "Russia", "Stockholm": "Sweden",
    "Oslo": "Norway", "Helsinki": "Finland", "Copenhagen": "Denmark",
    "Lisbon": "Portugal", "Madrid": "Spain", "Barcelona": "Spain",
    "Milan": "Italy", "Rome": "Italy", "Athens": "Greece",
    "New York": "United States", "Washington DC": "United States",
    "Miami": "United States", "Atlanta": "United States", "Boston": "United States",
    "Chicago": "United States", "Dallas": "United States", "Denver": "United States",
    "Houston": "United States", "Los Angeles": "United States",
    "San Francisco": "United States", "Seattle": "United States",
    "Phoenix": "United States", "Philadelphia": "United States",
    "Pittsburgh": "United States", "Las Vegas": "United States",
    "Toronto": "Canada", "Montreal": "Canada", "Vancouver": "Canada",
    "Ottawa": "Canada", "Calgary": "Canada", "Mexico City": "Mexico",
    "Bogota": "Colombia", "Lima": "Peru", "Sao Paulo": "Brazil",
    "Rio de Janeiro": "Brazil", "Buenos Aires": "Argentina", "Santiago": "Chile",
    "Singapore": "Singapore", "Hong Kong": "Hong Kong", "Tokyo": "Japan",
    "Osaka": "Japan", "Seoul": "South Korea", "Sydney": "Australia",
    "Melbourne": "Australia", "Brisbane": "Australia", "Perth": "Australia",
    "Auckland": "New Zealand", "Doha": "Qatar", "Dubai": "United Arab Emirates",
    "Tel Aviv": "Israel", "Jakarta": "Indonesia", "Bangkok": "Thailand",
    "Kuala Lumpur": "Malaysia", "Manila": "Philippines", "New Delhi": "India",
    "Mumbai": "India", "Bangalore": "India", "Chennai": "India",
    "Hyderabad": "India", "Cairo": "Egypt", "Casablanca": "Morocco",
    "Nairobi": "Kenya", "Lagos": "Nigeria",
}

# World PoP codes (city, region[optional]) — the same longest-token-first,
# delimiter-delimited rule as SA. Codes are unambiguous (doh/sin/hkg/...).
_WORLD_CITY_TOKENS: dict[str, tuple[str, str]] = {
    "paris": ("Paris", ""), "par": ("Paris", ""),
    "frankfurt": ("Frankfurt", ""), "fra": ("Frankfurt", ""),
    "munich": ("Munich", ""), "mun": ("Munich", ""),
    "berlin": ("Berlin", ""), "ber": ("Berlin", ""),
    "hamburg": ("Hamburg", ""), "ham": ("Hamburg", ""),
    "dusseldorf": ("Dusseldorf", ""), "dus": ("Dusseldorf", ""),
    "amsterdam": ("Amsterdam", ""), "ams": ("Amsterdam", ""),
    "rotterdam": ("Rotterdam", ""), "rot": ("Rotterdam", ""),
    "london": ("London", ""), "lon": ("London", ""), "lhr": ("London", ""),
    "manchester": ("Manchester", ""), "man": ("Manchester", ""),
    "glasgow": ("Glasgow", ""), "dublin": ("Dublin", ""), "dub": ("Dublin", ""),
    "brussels": ("Brussels", ""), "bru": ("Brussels", ""),
    "zurich": ("Zurich", ""), "zrh": ("Zurich", ""),
    "geneva": ("Geneva", ""), "gva": ("Geneva", ""),
    "vienna": ("Vienna", ""), "vie": ("Vienna", ""),
    "prague": ("Prague", ""), "prg": ("Prague", ""),
    "warsaw": ("Warsaw", ""), "waw": ("Warsaw", ""),
    "budapest": ("Budapest", ""), "bud": ("Budapest", ""),
    "bucharest": ("Bucharest", ""), "buh": ("Bucharest", ""),
    "sofia": ("Sofia", ""), "sof": ("Sofia", ""),
    "istanbul": ("Istanbul", ""), "ist": ("Istanbul", ""),
    "moscow": ("Moscow", ""), "mow": ("Moscow", ""),
    "stockholm": ("Stockholm", ""), "sto": ("Stockholm", ""),
    "oslo": ("Oslo", ""), "helsinki": ("Helsinki", ""), "hel": ("Helsinki", ""),
    "copenhagen": ("Copenhagen", ""), "cph": ("Copenhagen", ""), "cop": ("Copenhagen", ""),
    "lisbon": ("Lisbon", ""), "lis": ("Lisbon", ""),
    "madrid": ("Madrid", ""), "mad": ("Madrid", ""),
    "barcelona": ("Barcelona", ""), "bcn": ("Barcelona", ""),
    "milan": ("Milan", ""), "mil": ("Milan", ""),
    "rome": ("Rome", ""), "rom": ("Rome", ""),
    "athens": ("Athens", ""), "ath": ("Athens", ""),
    "new york": ("New York", ""), "nyc": ("New York", ""),
    "washington dc": ("Washington DC", ""), "wdc": ("Washington DC", ""),
    "miami": ("Miami", ""), "mia": ("Miami", ""),
    "atlanta": ("Atlanta", ""), "atl": ("Atlanta", ""),
    "boston": ("Boston", ""), "bos": ("Boston", ""),
    "chicago": ("Chicago", ""), "chi": ("Chicago", ""), "ord": ("Chicago", ""),
    "dallas": ("Dallas", ""), "dal": ("Dallas", ""), "dfw": ("Dallas", ""),
    "denver": ("Denver", ""), "den": ("Denver", ""),
    "houston": ("Houston", ""), "hou": ("Houston", ""),
    "los angeles": ("Los Angeles", ""), "lax": ("Los Angeles", ""),
    "san francisco": ("San Francisco", ""), "sfo": ("San Francisco", ""),
    "seattle": ("Seattle", ""), "sea": ("Seattle", ""),
    "phoenix": ("Phoenix", ""), "phx": ("Phoenix", ""),
    "philadelphia": ("Philadelphia", ""), "phl": ("Philadelphia", ""),
    "pittsburgh": ("Pittsburgh", ""), "las vegas": ("Las Vegas", ""), "las": ("Las Vegas", ""),
    "toronto": ("Toronto", ""), "tor": ("Toronto", ""), "yyz": ("Toronto", ""),
    "montreal": ("Montreal", ""), "mtl": ("Montreal", ""),
    "vancouver": ("Vancouver", ""), "van": ("Vancouver", ""),
    "ottawa": ("Ottawa", ""), "calgary": ("Calgary", ""),
    "mexico city": ("Mexico City", ""), "mex": ("Mexico City", ""),
    "bogota": ("Bogota", ""), "bog": ("Bogota", ""),
    "lima": ("Lima", ""), "lim": ("Lima", ""),
    "sao paulo": ("Sao Paulo", ""), "gru": ("Sao Paulo", ""),
    "rio de janeiro": ("Rio de Janeiro", ""), "rio": ("Rio de Janeiro", ""),
    "buenos aires": ("Buenos Aires", ""), "bue": ("Buenos Aires", ""), "eze": ("Buenos Aires", ""),
    "santiago": ("Santiago", ""), "scl": ("Santiago", ""),
    "singapore": ("Singapore", ""), "sin": ("Singapore", ""),
    "hong kong": ("Hong Kong", ""), "hkg": ("Hong Kong", ""),
    "tokyo": ("Tokyo", ""), "typ": ("Tokyo", ""), "tyo": ("Tokyo", ""),
    "osaka": ("Osaka", ""), "osa": ("Osaka", ""),
    "seoul": ("Seoul", ""), "sel": ("Seoul", ""),
    "sydney": ("Sydney", ""), "syd": ("Sydney", ""),
    "melbourne": ("Melbourne", ""), "mel": ("Melbourne", ""),
    "brisbane": ("Brisbane", ""), "bne": ("Brisbane", ""),
    "perth": ("Perth", ""), "per": ("Perth", ""),
    "auckland": ("Auckland", ""), "akl": ("Auckland", ""),
    "doha": ("Doha", ""), "doh": ("Doha", ""),
    "dubai": ("Dubai", ""), "dxb": ("Dubai", ""),
    "tel aviv": ("Tel Aviv", ""), "tlv": ("Tel Aviv", ""),
    "jakarta": ("Jakarta", ""), "cgk": ("Jakarta", ""),
    "bangkok": ("Bangkok", ""), "bkk": ("Bangkok", ""),
    "kuala lumpur": ("Kuala Lumpur", ""), "kul": ("Kuala Lumpur", ""),
    "manila": ("Manila", ""), "mnl": ("Manila", ""),
    "new delhi": ("New Delhi", ""), "del": ("New Delhi", ""),
    "mumbai": ("Mumbai", ""), "bom": ("Mumbai", ""),
    "bangalore": ("Bangalore", ""), "blr": ("Bangalore", ""),
    "chennai": ("Chennai", ""), "maa": ("Chennai", ""),
    "hyderabad": ("Hyderabad", ""), "hyd": ("Hyderabad", ""),
    "cairo": ("Cairo", ""), "cai": ("Cairo", ""),
    "casablanca": ("Casablanca", ""), "cmn": ("Casablanca", ""),
    "nairobi": ("Nairobi", ""), "nbo": ("Nairobi", ""),
    "lagos": ("Lagos", ""), "los": ("Lagos", ""),
}

_CITY_TOKENS: dict[str, tuple[str, str]] = dict(_SA_CITY_TOKENS)
_CITY_TOKENS.update(_WORLD_CITY_TOKENS)

# City center coordinates for map pins (SA + world PoP cities).
_WORLD_CITY_COORDS: dict[str, tuple[float, float]] = {
    "Paris": (48.8566, 2.3522), "Frankfurt": (50.1109, 8.6821),
    "Munich": (48.1372, 11.5755), "Berlin": (52.5200, 13.4050),
    "Hamburg": (53.5511, 9.9937), "Dusseldorf": (51.2277, 6.7735),
    "Amsterdam": (52.3676, 4.9041), "Rotterdam": (51.9244, 4.4777),
    "London": (51.5074, -0.1278), "Manchester": (53.4808, -2.2426),
    "Glasgow": (55.8642, -4.2518), "Dublin": (53.3498, -6.2603),
    "Brussels": (50.8503, 4.3517), "Zurich": (47.3769, 8.5417),
    "Geneva": (46.2044, 6.1432), "Vienna": (48.2082, 16.3738),
    "Prague": (50.0755, 14.4378), "Warsaw": (52.2297, 21.0122),
    "Budapest": (47.4979, 19.0402), "Bucharest": (44.4268, 26.1025),
    "Sofia": (42.6977, 23.3219), "Istanbul": (41.0082, 28.9784),
    "Moscow": (55.7558, 37.6173), "Stockholm": (59.3293, 18.0686),
    "Oslo": (59.9139, 10.7522), "Helsinki": (60.1699, 24.9384),
    "Copenhagen": (55.6761, 12.5683), "Lisbon": (38.7223, -9.1393),
    "Madrid": (40.4168, -3.7038), "Barcelona": (41.3874, 2.1686),
    "Milan": (45.4642, 9.1900), "Rome": (41.9028, 12.4964),
    "Athens": (37.9838, 23.7275), "New York": (40.7128, -74.0060),
    "Washington DC": (38.9072, -77.0369), "Miami": (25.7617, -80.1918),
    "Atlanta": (33.7490, -84.3880), "Boston": (42.3601, -71.0589),
    "Chicago": (41.8781, -87.6298), "Dallas": (32.7767, -96.7970),
    "Denver": (39.7392, -104.9903), "Houston": (29.7604, -95.3698),
    "Los Angeles": (34.0522, -118.2437), "San Francisco": (37.7749, -122.4194),
    "Seattle": (47.6062, -122.3321), "Phoenix": (33.4484, -112.0740),
    "Philadelphia": (39.9526, -75.1652), "Pittsburgh": (40.4406, -79.9959),
    "Las Vegas": (36.1699, -115.1398), "Toronto": (43.6532, -79.3832),
    "Montreal": (45.5017, -73.5673), "Vancouver": (49.2827, -123.1207),
    "Ottawa": (45.4215, -75.6972), "Calgary": (51.0447, -114.0719),
    "Mexico City": (19.4326, -99.1332), "Bogota": (4.7110, -74.0721),
    "Lima": (-12.0464, -77.0428), "Sao Paulo": (-23.5505, -46.6333),
    "Rio de Janeiro": (-22.9068, -43.1729), "Buenos Aires": (-34.6037, -58.3816),
    "Santiago": (-33.4489, -70.6693), "Singapore": (1.3521, 103.8198),
    "Hong Kong": (22.3193, 114.1694), "Tokyo": (35.6762, 139.6503),
    "Osaka": (34.6937, 135.5023), "Seoul": (37.5665, 126.9780),
    "Sydney": (-33.8688, 151.2093), "Melbourne": (-37.8136, 144.9631),
    "Brisbane": (-27.4698, 153.0251), "Perth": (-31.9505, 115.8605),
    "Auckland": (-36.8509, 174.7645), "Doha": (25.2854, 51.5310),
    "Dubai": (25.2048, 55.2708), "Tel Aviv": (32.0853, 34.7818),
    "Jakarta": (-6.2088, 106.8456), "Bangkok": (13.7563, 100.5018),
    "Kuala Lumpur": (3.1390, 101.6869), "Manila": (14.5995, 120.9842),
    "New Delhi": (28.7041, 77.1025), "Mumbai": (19.0760, 72.8777),
    "Bangalore": (12.9716, 77.5946), "Chennai": (13.0827, 80.2707),
    "Hyderabad": (17.3850, 78.4867), "Cairo": (30.0444, 31.2357),
    "Casablanca": (33.5731, -7.5898), "Nairobi": (-1.2921, 36.8219),
    "Lagos": (6.5244, 3.3792),
}


# Hand-verified (AFRINIC/allocation-informed) city for specific ISP prefixes.
# Grows ISP-by-ISP as verified data arrives; an empty value means "no confident
# city" and falls through to hostname/AFRINIC/fallback.
_ISP_PREFIX_CITY: dict[str, tuple[str, str]] = {
    # ExitLag overlay / Axxess CGNAT pool: reverse-DNS gives real PoP names
    # (cf. 100-127-2-186.ip.ahisp.co.za) so let hostname parsing own these.
    "100.127.0.0/16": None,  # no fixed city - hostnames carry it
}

# Exact-IP facts for the ISP seen in testing (ahisp.co.za). The reverse-DNS
# hostnames are purely numeric (100-127-2-186.ip.ahisp.co.za ...) with no PoP
# code, so the ONLY reliable source here is a hand-verified table:
#   key   = exact IP, confirmed present in the measured route
#   value = (city, province) — verified against the user's own network
#   None  = awaiting verification. NEVER guess a city; show the raw IP instead.
# Cities below were supplied/confirmed by the user for the route
# PE(Gqeberha) -> Cape Town -> Johannesburg. Each labeled hop is visible in the
# app, so a swapped pair is a one-line correction here, not a re-deploy cycle.
_ISP_HOST_FACTS: dict[str, object] = {
    "100.127.128.203": ("Johannesburg", "Gauteng"),
    "100.127.2.186": ("Cape Town", "Western Cape"),
    "100.127.3.137": ("Cape Town", "Western Cape"),
    "100.127.4.150": ("Johannesburg", "Gauteng"),
}

# Per-/16 cache of RIR RDAP lookups: (city, region) | None | "failed"
_RIR_CACHE: dict[str, object] = {}

# Users fix their own ISP's hops in %APPDATA%\MaximumTweaks\city_overrides.json:
#   { "100.127.4.150": ["Johannesburg", "Gauteng"],
#     "prefix:102.130.0.0/16": ["Cape Town", "Western Cape"] }
# Loaded lazily once; user entries override the built-in table (any user in any
# country can correct their own route without a rebuild). Never throws.
_USER_CITY_FACTS: dict[str, object] = {}
_USER_CITY_LOADED = False


def _load_user_facts() -> dict[str, object]:
    global _USER_CITY_LOADED
    if _USER_CITY_LOADED:
        return _USER_CITY_FACTS
    _USER_CITY_LOADED = True
    try:
        import json
        import os
        base = os.environ.get("APPDATA") or ""
        path = os.path.join(base, "MaximumTweaks", "city_overrides.json")
        if path and os.path.isfile(path):
            data = json.loads(open(path, encoding="utf-8").read())
            for key, val in (data or {}).items():
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    _USER_CITY_FACTS[str(key).strip()] = (val[0], val[1])
    except Exception:
        pass
    return _USER_CITY_FACTS


def _city_from_prefix(ip: str):
    """City pinned by the static ISP tables (user overrides first, then the
    built-in exact-IP facts and prefix table)."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    users = _load_user_facts()
    fact = users.get(ip)
    if fact is not None:
        return fact
    for key, city in users.items():
        if key.startswith("prefix:") and city:
            try:
                if addr in ipaddress.ip_network(key[len("prefix:"):], strict=False):
                    return city
            except ValueError:
                pass
    fact = _ISP_HOST_FACTS.get(ip)
    if fact is not None:
        return fact
    for prefix, city in _ISP_PREFIX_CITY.items():
        if addr in ipaddress.ip_network(prefix, strict=False) and city:
            return city
    return None


def _rir_city(ip: str, timeout: float = 2.5):
    """Best-effort RDAP cross-reference that routes to the OWNING RIR
    (rdap.org -> RIPE/ARIN/APNIC/LACNIC/AFRINIC by IP), cached once per /16
    (v4) or /48 (v6).

    RIR allocation records rarely publish a real POP city, so this is
    deliberately the lowest-confidence source; the network is blacklisted for
    the process lifetime on a miss.
    """
    def _net(ip: str):
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return ""
        if a.version == 4:
            return str(ipaddress.ip_network(f"{ip}/16", strict=False).network_address)
        return str(ipaddress.ip_network(f"{ip}/48", strict=False).network_address)
    key = _net(ip)
    if not key:
        return None
    if key in _RIR_CACHE:
        v = _RIR_CACHE[key]
        return v if v != "failed" else None
    _RIR_CACHE[key] = "failed"  # blacklist until resolved
    try:
        import json
        import urllib.request

        req = urllib.request.Request(
            f"https://rdap.org/ip/{ip}",
            headers={"Accept": "application/rdap+json", "User-Agent": "MaximumTweaks/2.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        city = ""
        region = data.get("name", "") or ""
        for ent in data.get("entities", []) or []:
            vcard = ((ent.get("vcardArray") or [None, []])[1] or [])
            for item in vcard:
                if item and len(item) >= 3 and item[0] == "adr":
                    box = item[3]
                    if isinstance(box, dict):
                        city = box.get("locality", "") or city
        if city:
            _RIR_CACHE[key] = (city, region)
            return (city, region)
    except Exception:
        pass
    return None


def resolve_hop_city(hop, allow_rir: bool = True) -> bool:
    """Try to resolve a real city for `hop` (mutates hop.geo in place).

    Priority: reverse-DNS hostname PoP code > static table (per-user overrides,
    built-in facts, prefixes) > owning RIR RDAP (lowest confidence). A hit sets
    the geo city/province/country, marks the source, and pins coordinates when
    known. Returns True when a city was applied. Never throws (route enrichment
    must not fail on geo).
    """
    try:
        from engine.netmonitor.types import HopGeo
    except Exception:
        return False
    try:
        nt = (hop.network.network_type or "") if hop.network else ""
        if nt in ("anycast", "anycast_edge", "edge"):
            return False  # cloud/anycast boxes are handled by cloudmap/planner
        hit = _city_from_hostname(getattr(hop, "hostname", "") or "")
        source = "hostname"
        confid = 100
        if hit is None:
            hit = _city_from_prefix(getattr(hop, "ip", "") or "")
            source = "isp_prefix"
            confid = 90
        if hit is None and allow_rir:
            af = _rir_city(getattr(hop, "ip", "") or "")
            if af and af[0]:
                hit = (af[0], af[1] or "")
                source = "afrinic"
                confid = 40
        if hit is None:
            return False
        city, province = hit[0], hit[1]
        geo = getattr(hop, "geo", None)
        if geo is None:
            geo = HopGeo()
            hop.geo = geo
        # A hostname/prefix hit is authoritative (the ISP named the box / the
        # user pinned it); the country is the DB's value or the city's country.
        geo.city = city
        geo.region = province
        geo.country = geo.country or _CITY_COUNTRY.get(city, "South Africa")
        geo.approximate = confid < 90
        geo.verified = confid >= 90
        geo.city_source = source
        coords = _SA_CITY_COORDS.get(city) or _WORLD_CITY_COORDS.get(city)
        if coords:
            geo.latitude, geo.longitude = coords
        geo.hint = (
            f"city resolved from {'reverse-DNS hostname' if source == 'hostname'
            else 'ISP prefix table' if source == 'isp_prefix'
            else 'RIR RDAP allocation records'} "
            f"('{city}') - network operator naming, not a geo database"
        )
        return True
    except Exception:
        return False