"""Maximum Tweaks Admin - lightweight HTTP client for the license backend.

Talks to the same FastAPI service the web admin panel uses. Login exchanges
the operator's ADMIN_TOKEN for the server's HttpOnly session cookie; the raw
token is used once at login and never stored or re-sent. Every subsequent
request rides the in-memory cookie jar (Secure cookie over HTTPS).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Any


class ApiError(Exception):
    def __init__(self, message: str, code: str = "error", status: int = 0):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status

    def __str__(self) -> str:
        return self.message


class AdminClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._jar = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar))
        self._opener.addheaders = [("Accept", "application/json")]

    # -- requests ---------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self._opener.open(req, timeout=30) as resp:
                return self._parse(resp)
        except urllib.error.HTTPError as e:
            payload = None
            try:
                payload = json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                pass
            err = (payload or {}).get("error", "server_error")
            msg = (payload or {}).get("message", "") or str(e)
            if e.code == 401:
                raise ApiError("Not logged in (session expired). Sign in again.",
                               code="unauthorized", status=401)
            if e.code == 500:
                raise ApiError("The license server hit an internal error. "
                               "Try again in a moment.",
                               code="server_error", status=500)
            raise ApiError(msg, code=err or "request_failed", status=e.code)
        except urllib.error.URLError as e:
            raise ApiError(f"Cannot reach the license server ({e.reason}).",
                           code="network", status=0)

    @staticmethod
    def _parse(resp) -> dict:
        raw = resp.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "error": "bad_response",
                    "message": "Unexpected server response."}

    # -- auth -------------------------------------------------------------
    def login(self, token: str) -> None:
        self._jar.clear()
        self._request("POST", "/admin/login", {"token": token})

    def logout(self) -> None:
        try:
            self._request("POST", "/admin/logout")
        except ApiError:
            pass
        self._jar.clear()

    def me(self) -> dict:
        return self._request("GET", "/admin/me")

    def health(self) -> dict:
        return self._request("GET", "/health")

    # -- admin ------------------------------------------------------------
    def stats(self) -> dict:
        return self._request("GET", "/admin/stats")

    def licenses(self, status: str | None = None) -> list[dict]:
        q = f"?status={urllib.parse.quote(status)}" if status else ""
        data = self._request("GET", "/admin/licenses" + q)
        return data.get("licenses", [])

    def search(self, query: str) -> list[dict]:
        data = self._request("GET", "/admin/search?q=" + urllib.parse.quote(query))
        return data.get("licenses", [])

    def generate(self, count: int = 1, prefix: str = "", duration: str = "lifetime",
                 customer: str = "", note: str = "") -> dict:
        body = {"count": max(1, min(count, 500)), "duration": duration,
                "customer": customer or "", "note": note or ""}
        if prefix.strip():
            body["prefix"] = prefix.strip().upper()
        return self._request("POST", "/admin/generate", body)

    def revoke(self, key: str, reason: str = "") -> dict:
        return self._request("POST", "/admin/revoke", {"key": key, "reason": reason})

    def unrevoke(self, key: str) -> dict:
        return self._request("POST", "/admin/unrevoke", {"key": key})

    def unbind(self, key: str) -> dict:
        return self._request("POST", "/admin/unbind", {"key": key})

    def delete(self, key: str) -> dict:
        """Permanently delete a license row. Not recoverable."""
        return self._request("DELETE", "/admin/keys/" + urllib.parse.quote(key))


def mask_device(device_id: str | None) -> str:
    if not device_id:
        return "—"
    if len(device_id) <= 12:
        return device_id
    return device_id[:12] + "…"