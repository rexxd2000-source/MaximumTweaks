"""Auto-start / auto-stop for the auth backend.

The desktop app owns all Discord OAuth + verification, but the actual OAuth
work (Client Secret, bot token, join + role assignment) lives in the separate
FastAPI service under ``auth_backend/``. This module lets the app start that
service automatically when the app launches and stop it when the app closes,
so a user never has to run the backend by hand.

Rules:
  * If the backend is ALREADY reachable (someone is hosting it, or a dev left
    it running), we do not start our own copy and we do not stop the remote
    one — we just use it.
  * Otherwise we spawn ``auth_backend/main.py`` with uvicorn in a hidden
    console and poll ``/health`` until it responds.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from config.app_config import AUTH_SERVER_URL
from rexlog import logger

_port, _host = 8000, "127.0.0.1"
_proc: subprocess.Popen | None = None
_started_by_us = False

_HEALTH_PATH = "/health"


def _health_ok(timeout: float = 5.0) -> bool:
    url = f"{AUTH_SERVER_URL.rstrip('/')}{_HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def start() -> bool:
    """Ensure the auth backend is reachable, starting it if needed.

    Returns True if the backend is reachable, False otherwise.
    """
    global _proc, _started_by_us

    if _health_ok():
        logger.info("auth-server: already reachable, using existing backend")
        return True

    # The auth backend runs under the same Python install as the app.
    backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "auth_backend")
    main_py = os.path.join(backend_dir, "main.py")
    if not os.path.exists(main_py):
        logger.warn("auth-server: auth_backend/main.py not found — cannot "
                    "auto-start backend")
        return False

    # Run uvicorn with a hidden console (CREATE_NO_WINDOW) and stdout/stderr
    # redirected to log files so nothing flashes on screen.
    flags = 0
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0x08000000
    out = os.path.join(backend_dir, "server.out.log")
    err = os.path.join(backend_dir, "server.err.log")
    try:
        _proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app",
             "--host", _host, "--port", str(_port)],
            cwd=backend_dir,
            creationflags=flags,
            stdout=open(out, "a", encoding="utf-8"),
            stderr=open(err, "a", encoding="utf-8"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"auth-server: could not start backend: {exc}")
        return False

    # Wait for the backend to become healthy.
    deadline = time.time() + 30
    while time.time() < deadline:
        if _health_ok():
            _started_by_us = True
            logger.info("auth-server: backend started and healthy")
            return True
        if _proc.poll() is not None:
            logger.warn("auth-server: backend process exited early "
                        f"(code {_proc.returncode})")
            return False
        time.sleep(0.5)

    logger.warn("auth-server: backend did not become healthy in time")
    return False


def stop() -> None:
    """Stops the backend ONLY if this app started it."""
    global _proc, _started_by_us
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.terminate()
            try:
                _proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proc.kill()
                _proc.wait(timeout=5)
            logger.info("auth-server: stopped backend (started by this app)")
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"auth-server: failed to stop backend: {exc}")
    _proc = None
    _started_by_us = False
