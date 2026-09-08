"""Rex Tweaks logging system.

Writes a rotating log file to Logs/rextweaks.log and optionally mirrors
to the console. Logs application events, hardware detection, applied and
reverted tweaks, errors and failed operations.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from config.app_config import LOG_FILE

_initialized = False
_ui_sink = None  # callable(message) that the GUI can register to display live logs


def register_ui_sink(fn):
    global _ui_sink
    _ui_sink = fn


def _make_logger() -> logging.Logger:
    global _initialized
    logger = logging.getLogger("rextweaks")
    if _initialized:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_500_000, backupCount=4, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    console.setLevel(logging.INFO)
    logger.addHandler(console)

    _initialized = True
    return logger


class RexLogger:
    """Thin facade over the standard logging module with GUI sink support."""

    def __init__(self):
        self._log = _make_logger()

    def _emit(self, level, msg):
        self._log.log(level, msg)
        if _ui_sink is not None:
            try:
                _ui_sink(f"[{logging.getLevelName(level)}] {msg}")
            except Exception:
                pass

    def debug(self, msg):  self._emit(logging.DEBUG, msg)
    def info(self, msg):   self._emit(logging.INFO, msg)
    def warn(self, msg):   self._emit(logging.WARNING, msg)
    def error(self, msg):  self._emit(logging.ERROR, msg)
    def critical(self, msg): self._emit(logging.CRITICAL, msg)

    def log_tweak_applied(self, tweak_id, name):
        self.info(f"TWEAK APPLIED  | {tweak_id} | {name}")

    def log_tweak_reverted(self, tweak_id, name):
        self.info(f"TWEAK REVERTED | {tweak_id} | {name}")

    def log_operation(self, op, detail):
        self.info(f"OPERATION      | {op} | {detail}")


logger = RexLogger()
