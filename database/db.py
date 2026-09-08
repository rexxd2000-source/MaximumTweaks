"""Tweak database loader.

Loads every ``database/tweaks/*.py`` category module, validates it and
builds an in-memory index. Can also export the whole database to a JSON
file (``database/tweaks.json``) so the data stays separate from the code
and is easy to inspect or extend.
"""
from __future__ import annotations

import importlib
import json
import pkgutil
import re
from collections import OrderedDict

from config.app_config import DB_JSON_EXPORT, DIRS
from rexlog import logger

_CATEGORY_ORDER = [
    "Windows", "System", "CPU", "GPU", "RAM", "Storage", "Network", "Ethernet",
    "Wi-Fi", "Keyboard", "Mouse", "USB", "Audio", "Monitor", "Display",
    "NVIDIA", "AMD", "Intel", "Gaming", "Fortnite", "Game Profiles",
    "Services", "Startup", "Background Apps", "Windows Explorer", "Registry",
    "Power", "Power Plans", "Scheduling", "Input Latency", "FPS",
    "Frame Time", "DirectX", "DirectX 12", "Windows Graphics",
    "Security/Performance", "Telemetry", "Debloating", "Privacy",
    "Advanced Tweaks", "Experimental Tweaks", "Diagnostics", "Repair Tools",
    "System Tools", "BIOS Guidance",
]

_SEARCH_EXTRA = {
    "input latency": ["latency", "input", "mouse", "keyboard", "usb", "polling", "buffer"],
    "fps": ["fps", "framerate", "frames", "performance"],
    "frame time": ["frametime", "pacing", "stutter", "smooth"],
}


class TweakDatabase:
    """In-memory index over the category modules."""

    def __init__(self):
        self.tweaks: dict[str, dict] = {}
        self.by_category: OrderedDict[str, list[dict]] = OrderedDict()
        self.categories: list[str] = []
        self.errors: list[str] = []

    def load(self, path=None, export_json=True):
        path = path or (DIRS["database"] / "tweaks")
        for mod in pkgutil.iter_modules([str(path)]):
            if mod.name.startswith("_"):
                continue
            try:
                module = importlib.import_module(f"database.tweaks.{mod.name}")
                cat = getattr(module, "CATEGORY", None) or mod.name.replace("_", " ").title()
                items = list(getattr(module, "TWEAKS", []))
                if not items:
                    logger.warn(f"Database: {mod.name} has no tweaks")
                    continue
                for t in items:
                    t["category"] = cat
                    self.tweaks[t["id"]] = t
                self.by_category.setdefault(cat, []).extend(items)
                logger.info(f"Loaded {len(items)} tweaks from category {cat}")
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{mod.name}: {exc}")
                logger.error(f"Failed to load database module {mod.name}: {exc}")
        # order categories
        ordered = [c for c in _CATEGORY_ORDER if c in self.by_category]
        ordered += [c for c in self.by_category if c not in ordered]
        self.categories = ordered
        self.by_category = OrderedDict((c, self.by_category[c]) for c in ordered)
        if export_json:
            try:
                DB_JSON_EXPORT.parent.mkdir(parents=True, exist_ok=True)
                DB_JSON_EXPORT.write_text(
                    json.dumps({"count": len(self.tweaks),
                                "tweaks": list(self.tweaks.values())},
                               indent=1),
                    encoding="utf-8")
                logger.info(f"Exported tweak database to {DB_JSON_EXPORT.name}")
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Could not export JSON database: {exc}")
        logger.info(f"Database ready: {len(self.tweaks)} tweaks across {len(self.categories)} categories")
        return self

    # ---- queries ------------------------------------------------------
    def all(self):
        return list(self.tweaks.values())

    def get(self, tweak_id):
        return self.tweaks.get(tweak_id)

    def by_cat(self, category):
        return list(self.by_category.get(category, []))

    def count_by_cat(self):
        return {c: len(items) for c, items in self.by_category.items()}

    def search(self, query, limit=200):
        """Search tweak names, categories, descriptions, tags and hardware terms."""
        q = query.strip().lower()
        if not q:
            return self.all()[:limit]
        terms = [t for t in re.split(r"[\s,]+", q) if t]
        hits = []
        for t in self.tweaks.values():
            haystack = " ".join([
                t["name"], t["desc"], t["category"], t.get("why", ""),
                t.get("changes", ""), " ".join(t.get("tags", [])),
            ]).lower()
            for extra_key, extra_terms in _SEARCH_EXTRA.items():
                if q in extra_key or extra_key in q:
                    haystack += " " + " ".join(extra_terms)
            if all(term in haystack for term in terms):
                hits.append(t)
        hits.sort(key=lambda t: t["name"].lower().startswith(q), reverse=True)
        return hits[:limit]
