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
  * In frozen (PyInstaller) builds the FastAPI app is bundled inside the exe
    and is started in-process on a background thread — end users need no
    Python install. Its secrets come from a ``.env`` next to the exe.
  * In dev we spawn ``auth_backend/main.py`` with uvicorn in a hidden console
    and poll ``/health`` until it responds.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from config.app_config import AUTH_SERVER_URL, ROOT
from rexlog import logger

_port, _host = 8000, "127.0.0.1"
_proc: subprocess.Popen | None = None
_server = None  # uvicorn.Server when running in-process
_server_thread: threading.Thread | None = None
_started_by_us = False

_HEALTH_PATH = "/health"


def _health_ok(timeout: float = 5.0) -> bool:
    url = f"{AUTH_SERVER_URL.rstrip('/')}{_HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _load_backend_env() -> None:
    """Load the ``.env`` that configures the bundled FastAPI backend.

    Frozen builds have no Python or source tree, so the app must read the
    Discord credentials from a ``.env`` living next to the exe (ROOT). In dev
    we prefer ``auth_backend/.env``. load_dotenv never overrides real env vars.
    """
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001
        return
    candidates = []
    if not getattr(sys, "frozen", False):
        candidates.append(Path(__file__).resolve().parent.parent / "auth_backend" / ".env")
    candidates.append(Path(ROOT) / ".env")
    for env_file in candidates:
        if env_file.is_file():
            try:
                load_dotenv(str(env_file), override=False)
                logger.info(f"auth-server: loaded backend env from {env_file}")
            except Exception:  # noqa: BLE001
                logger.warn(f"auth-server: could not read {env_file}")
            return


def _start_subprocess(backend_dir: Path) -> bool:
    """Dev mode: spawn ``auth_backend/main.py`` with uvicorn in a hidden console."""
    main_py = backend_dir / "main.py"
    if not main_py.exists():
        logger.warn("auth-server: auth_backend/main.py not found — cannot "
                    "auto-start backend")
        return False
    flags = 0
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0x08000000
    out = backend_dir / "server.out.log"
    err = backend_dir / "server.err.log"
    try:
        global _proc
        _proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app",
             "--host", _host, "--port", str(_port)],
            cwd=str(backend_dir),
            creationflags=flags,
            stdout=open(out, "a", encoding="utf-8"),
            stderr=open(err, "a", encoding="utf-8"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"auth-server: could not start backend: {exc}")
        return False
    return True


def _start_inprocess() -> bool:
    """Frozen mode: run the bundled FastAPI backend on a background thread.

    This is what makes Discord verification work for end users — the backend
    is compiled into the exe, so it starts with the app and needs no Python.
    """
    global _server, _server_thread
    if importlib.util.find_spec("auth_backend.main") is None:
        logger.warn("auth-server: auth_backend not bundled in this build")
        return False
    try:
        import uvicorn
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"auth-server: uvicorn not bundled ({exc})")
        return False

    _load_backend_env()

    # "auth_backend.main:app" is imported lazily by uvicorn inside the thread,
    # AFTER the env above is loaded, so the module-level config reads are valid.
    config = uvicorn.Config("auth_backend.main:app", host=_host, port=_port,
                            log_level="warning")
    _server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=_server.run, daemon=True,
                                      name="rex-auth-backend")
    _server_thread.start()
    logger.info("auth-server: starting bundled backend in-process")
    return True


def start() -> bool:
    """Ensure the auth backend is reachable, starting it if needed.

    Returns True if the backend is reachable, False otherwise.
    """
    global _started_by_us

    if _health_ok():
        logger.info("auth-server: already reachable, using existing backend")
        return True

    if getattr(sys, "frozen", False):
        ok = _start_inprocess()
    else:
        backend_dir = Path(__file__).resolve().parent.parent / "auth_backend"
        ok = _start_subprocess(backend_dir)

    if not ok:
        return False

    # Wait for the backend to become healthy.
    deadline = time.time() + 30
    while time.time() < deadline:
        if _health_ok():
            _started_by_us = True
            logger.info("auth-server: backend started and healthy")
            return True
        if _proc is not None and _proc.poll() is not None:
            logger.warn("auth-server: backend process exited early "
                        f"(code {_proc.returncode})")
            return False
        time.sleep(0.5)

    logger.warn("auth-server: backend did not become healthy in time")
    return False


def stop() -> None:
    """Stops the backend ONLY if this app started it."""
    global _proc, _server, _server_thread, _started_by_us
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
    if _server is not None:
        _server.should_exit = True
        if _server_thread is not None:
            _server_thread.join(timeout=5)
        logger.info("auth-server: stopped bundled backend")
    _server = None
    _server_thread = None
    _proc = None
    _started_by_us = False
