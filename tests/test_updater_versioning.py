"""Version comparison used by the updater's update gate.

The prerelease cases are load-bearing for the rc release flow: a build
tagged v2.5.3-rc1 must see the stable manifest (2.5.2) as *not* newer
(otherwise every rc user is offered a silent downgrade to stable), stable
users must never be offered an rc, and the eventual 2.5.3 release must
reach both populations.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.updater import is_newer, parse_version  # noqa: E402

CASES = [
    # (remote, local, expected)
    ("2.5.3", "2.5.2", True),          # plain upgrade
    ("2.5.2", "2.5.3", False),
    ("2.5.2", "2.5.2", False),         # same
    ("2.5.3-rc1", "2.5.2", True),      # rc contains newer code than old stable
    ("2.5.2", "2.5.3-rc1", False),     # ... but the stable manifest is never
                                       # an "update" for an rc build
    ("2.5.3", "2.5.3-rc1", True),      # release reaches rc users
    ("2.5.3-rc1", "2.5.3", False),     # rc never reaches release users
    ("2.5.3-rc2", "2.5.3-rc1", True),  # rc ordering
    ("2.5.3-rc1", "2.5.3-rc2", False),
    ("v2.5.3", "2.5.3", False),        # v-prefix normalizes away
    ("2.5.3", "v2.5.2", True),
]


@pytest.mark.parametrize("remote,local,expected", CASES)
def test_is_newer(remote, local, expected):
    assert is_newer(remote, local) is expected


def test_parse_version_shape():
    assert parse_version("v1.2.3-beta") == ((1, 2, 3), ("beta",))
    assert parse_version("2.5.3-rc1") == ((2, 5, 3), ("rc1",))
    assert parse_version("2.5.2") == ((2, 5, 2), ())
