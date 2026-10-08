"""The served update manifest must parse for every user.

Regression: release.ps1 wrote update.json with PowerShell's UTF-8 BOM, which
json.load rejected — the broad except turned that into HTTP 502 on
/update.json for every installed app, so nobody could receive updates.
"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("LICENSE_SECRET", "test-secret-not-for-production")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("SESSION_TTL_HOURS", "2")
os.environ.setdefault("OFFLINE_GRACE_HOURS", "24")

from fastapi.testclient import TestClient  # noqa: E402

import main as backend  # noqa: E402

client = TestClient(backend.app)


def test_update_manifest_serves_repo_file():
    resp = client.get("/update.json")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("version")
    assert data.get("url")
    # The release gate requires installer fields for NSIS-installed copies.
    assert data.get("installer_url")
    assert data.get("installer_checksum_url")


def test_update_manifest_tolerates_utf8_bom(monkeypatch):
    payload = json.dumps({"version": "9.9.9", "url": "https://cdn/x.exe"})
    bom_path = os.path.join(tempfile.gettempdir(), "mt_update_bom.json")
    with open(bom_path, "wb") as fh:
        fh.write(b"\xef\xbb\xbf" + payload.encode("utf-8"))
    monkeypatch.setattr(backend, "_UPDATE_MANIFEST_FILE", bom_path)
    resp = client.get("/update.json")
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == "9.9.9"


def test_update_manifest_missing_file_fails_closed(monkeypatch):
    monkeypatch.setattr(
        backend, "_UPDATE_MANIFEST_FILE",
        os.path.join(tempfile.gettempdir(), "mt_update_missing.json"))
    resp = client.get("/update.json")
    assert resp.status_code == 502
    assert resp.json().get("status") == "error"
