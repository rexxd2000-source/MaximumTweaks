#!/usr/bin/env python3
"""Build geo_data.py from sections."""
import sys, os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_data.py")

def w(f, s):
    f.write(s)

with open(OUT, "w", encoding="utf-8") as f:
    w(f, '"""\nSimplified but accurate geographical data for a 3D globe renderer.\n')
    w(f, 'Contains country boundaries, major cities, IXPs, subsea cables, and BGP hubs.\n')
    w(f, 'All coordinates are (lat, lon) tuples.\n"""\n\n\n')

    # Read each section file
    base = os.path.dirname(os.path.abspath(__file__))
    sections = ["africa", "europe", "asia", "namericas", "samericas", "oceania",
                "cities", "ixps", "cables", "bgp"]
    for sec in sections:
        p = os.path.join(base, f"_s_{sec}.py")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as sf:
                f.write(sf.read())
            f.write("\n\n")

    # Build COUNTRIES from regional dicts
    w(f, "COUNTRIES = {}\n")
    for sec in ["africa", "europe", "asia", "namericas", "samericas", "oceania"]:
        w(f, f"COUNTRIES.update({sec})\n")

    print(f"Wrote {os.path.getsize(OUT)} bytes to {OUT}")
