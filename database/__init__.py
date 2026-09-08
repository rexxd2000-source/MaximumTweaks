"""Database package — the Maximum Tweaks tweak registry."""
from __future__ import annotations

from . import tweaks
from .tweaks import TWEAKS, BY_ID, CATEGORIES

__all__ = ["TWEAKS", "BY_ID", "CATEGORIES", "tweaks"]
