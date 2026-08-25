"""Convert Natural Earth TopoJSON to globe.gl polygon format."""
import json
import urllib.request
import os
import sys

# Fetch the TopoJSON
url = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json"
print(f"Fetching {url}...")
req = urllib.request.Request(url, headers={"User-Agent": "MaximumTweaks/1.0"})
with urllib.request.urlopen(req, timeout=30) as resp:
    topo = json.loads(resp.read().decode())

# Simple TopoJSON to GeoJSON converter for objects.countries
objects = topo["objects"]
arcs = topo["arcs"]
transform = topo.get("transform", {})

def decode_arc(arc_idx):
    """Decode an arc from TopoJSON delta encoding."""
    if arc_idx < 0:
        arc_idx = ~arc_idx
    arc = arcs[arc_idx]
    coords = []
    x, y = 0, 0
    for dx, dy in arc:
        x += dx
        y += dy
        coords.append((x, y))
    return coords

def transform_coords(coords):
    """Apply TopoJSON transform to quantized coordinates."""
    if not transform:
        return coords
    sx = transform.get("scale", [1, 1])
    tx = transform.get("translate", [0, 0])
    return [
        (x * sx[0] + tx[0], y * sx[1] + tx[1])
        for x, y in coords
    ]

def decode_ring(ring_arcs):
    """Decode a ring from arc references."""
    coords = []
    for arc_idx in ring_arcs:
        arc = decode_arc(arc_idx)
        if coords and arc:
            arc = arc[1:]  # skip first point (same as last of previous)
        coords.extend(arc)
    return coords

# Country name lookup (ISO numeric -> name)
COUNTRY_NAMES = {
    "004": "Afghanistan", "008": "Albania", "012": "Algeria", "024": "Angola",
    "032": "Argentina", "036": "Australia", "040": "Austria", "050": "Bangladesh",
    "056": "Belgium", "064": "Bhutan", "068": "Bolivia", "070": "Bosnia and Herzegovina",
    "072": "Botswana", "076": "Brazil", "096": "Brunei", "100": "Bulgaria",
    "104": "Myanmar", "116": "Cambodia", "120": "Cameroon", "124": "Canada",
    "140": "Central African Republic", "144": "Sri Lanka", "148": "Chad",
    "152": "Chile", "156": "China", "170": "Colombia", "178": "Republic of the Congo",
    "180": "Democratic Republic of the Congo", "188": "Costa Rica", "191": "Croatia",
    "192": "Cuba", "196": "Cyprus", "203": "Czech Republic", "204": "Benin",
    "208": "Denmark", "214": "Dominican Republic", "218": "Ecuador", "818": "Egypt",
    "222": "El Salvador", "226": "Equatorial Guinea", "232": "Eritrea",
    "233": "Estonia", "231": "Ethiopia", "246": "Finland", "250": "France",
    "266": "Gabon", "270": "Gambia", "268": "Georgia", "276": "Germany",
    "288": "Ghana", "300": "Greece", "320": "Guatemala", "324": "Guinea",
    "328": "Guyana", "332": "Haiti", "340": "Honduras", "348": "Hungary",
    "352": "Iceland", "356": "India", "360": "Indonesia", "364": "Iran",
    "368": "Iraq", "372": "Ireland", "376": "Israel", "380": "Italy",
    "384": "Ivory Coast", "388": "Jamaica", "392": "Japan", "400": "Jordan",
    "398": "Kazakhstan", "404": "Kenya", "414": "Kuwait", "417": "Kyrgyzstan",
    "418": "Laos", "422": "Lebanon", "426": "Lesotho", "430": "Liberia",
    "434": "Libya", "440": "Lithuania", "442": "Luxembourg", "450": "Madagascar",
    "454": "Malawi", "458": "Malaysia", "466": "Mali", "478": "Mauritania",
    "484": "Mexico", "496": "Mongolia", "504": "Morocco", "508": "Mozambique",
    "516": "Namibia", "524": "Nepal", "528": "Netherlands", "554": "New Zealand",
    "558": "Nicaragua", "562": "Niger", "566": "Nigeria", "578": "Norway",
    "512": "Oman", "586": "Pakistan", "591": "Panama", "598": "Papua New Guinea",
    "600": "Paraguay", "604": "Peru", "608": "Philippines", "616": "Poland",
    "620": "Portugal", "634": "Qatar", "642": "Romania", "643": "Russia",
    "646": "Rwanda", "682": "Saudi Arabia", "686": "Senegal", "694": "Sierra Leone",
    "702": "Singapore", "703": "Slovakia", "704": "Vietnam", "705": "Slovenia",
    "706": "Somalia", "710": "South Africa", "716": "Zimbabwe",
    "724": "Spain", "144": "Sri Lanka", "729": "Sudan", "740": "Suriname",
    "748": "Eswatini", "752": "Sweden", "756": "Switzerland", "760": "Syria",
    "762": "Tajikistan", "764": "Thailand", "768": "Togo", "780": "Trinidad and Tobago",
    "788": "Tunisia", "792": "Turkey", "795": "Turkmenistan", "800": "Uganda",
    "804": "Ukraine", "784": "United Arab Emirates", "826": "United Kingdom",
    "834": "Tanzania", "840": "United States", "854": "Burkina Faso",
    "858": "Uruguay", "860": "Uzbekistan", "862": "Venezuela", "887": "Yemen",
    "894": "Zambia", "158": "Taiwan",
}

# Decode countries
countries = objects.get("countries", {"geometries": []})
geometries = countries.get("geometries", [])

output_polygons = []
output_labels = []

for geom in geometries:
    props = geom.get("properties", {})
    country_id = props.get("id", "")
    country_name = props.get("name", COUNTRY_NAMES.get(str(country_id), f"ID:{country_id}"))
    geom_type = geom.get("type", "")

    if geom_type == "Polygon":
        rings = geom.get("arcs", [])
        coords = []
        for ring_arcs in rings:
            decoded = decode_ring(ring_arcs)
            transformed = transform_coords(decoded)
            coords.append([[lat, lon] for lon, lat in transformed])
        if coords:
            output_polygons.append({
                "name": country_name,
                "id": country_id,
                "polygons": coords,
            })
            # Compute centroid for label
            all_pts = coords[0]
            if all_pts:
                clat = sum(p[0] for p in all_pts) / len(all_pts)
                clon = sum(p[1] for p in all_pts) / len(all_pts)
                output_labels.append({
                    "lat": round(clat, 2),
                    "lng": round(clon, 2),
                    "name": country_name,
                })

    elif geom_type == "MultiPolygon":
        all_coords = []
        for polygon in geom.get("arcs", []):
            poly_coords = []
            for ring_arcs in polygon:
                decoded = decode_ring(ring_arcs)
                transformed = transform_coords(decoded)
                poly_coords.append([[lat, lon] for lon, lat in transformed])
            if poly_coords:
                all_coords.append(poly_coords)
        if all_coords:
            output_polygons.append({
                "name": country_name,
                "id": country_id,
                "polygons": all_coords,
            })
            # Compute centroid from first polygon
            if all_coords and all_coords[0]:
                all_pts = all_coords[0][0]
                if all_pts:
                    clat = sum(p[0] for p in all_pts) / len(all_pts)
                    clon = sum(p[1] for p in all_pts) / len(all_pts)
                    output_labels.append({
                        "lat": round(clat, 2),
                        "lng": round(clon, 2),
                        "name": country_name,
                    })

# Major country labels (show at global zoom)
MAJOR_COUNTRIES = {
    "United States", "Canada", "Brazil", "Argentina", "Mexico",
    "United Kingdom", "France", "Germany", "Spain", "Italy", "Norway", "Sweden", "Finland",
    "Russia", "China", "India", "Japan", "South Korea", "Mongolia",
    "Australia", "New Zealand",
    "South Africa", "Nigeria", "Egypt", "Kenya", "Ethiopia", "Morocco", "Algeria", "Tanzania", "Democratic Republic of the Congo",
    "Saudi Arabia", "Turkey", "Iran", "Iraq", "Israel", "United Arab Emirates",
    "Indonesia", "Thailand", "Vietnam", "Philippines", "Malaysia", "Pakistan", "Kazakhstan",
}

major_labels = [l for l in output_labels if l["name"] in MAJOR_COUNTRIES]

print(f"Countries: {len(output_polygons)}")
print(f"Labels: {len(output_labels)} ({len(major_labels)} major)")
print(f"Sample: {output_polygons[0]['name'] if output_polygons else 'none'}")

# Save as JS module
output_path = os.path.join(os.path.dirname(__file__), "assets", "countries.js")
with open(output_path, "w") as f:
    f.write("// Auto-generated from Natural Earth 110m — do not edit manually\n")
    f.write(f"const COUNTRIES = {json.dumps(output_polygons, separators=(',', ':'))};\n")
    f.write(f"const COUNTRY_LABELS = {json.dumps(output_labels, separators=(',', ':'))};\n")
    f.write(f"const MAJOR_COUNTRY_LABELS = {json.dumps(major_labels, separators=(',', ':'))};\n")

size_kb = os.path.getsize(output_path) / 1024
print(f"Saved to {output_path} ({size_kb:.0f} KB)")
