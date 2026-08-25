"""Continuous ping monitor for destination and individual hops."""
from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import Optional

from engine.netmonitor.types import HopProbes, RouteEvent


class PingMonitor:
    """Background continuous ping to a target, collecting latency history."""

    def __init__(
        self,
        target: str,
        interval: float = 2.0,
        count: int = 60,
        on_sample=None,
        on_event=None,
    ):
        self.target = target
        self.interval = interval
        self.max_count = count
        self.on_sample = on_sample
        self.on_event = on_event
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.samples: list[tuple[float, float]] = []
        self.current_probes = HopProbes()
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self):
        count = 0
        while not self._stop.is_set() and count < self.max_count:
            start = time.time()
            try:
                cmd = ["ping", "-n", "1", "-w", "2000", self.target]
                creation_flags = 0x08000000
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=creation_flags,
                )
                match = re.search(r"time[=<](\d+)ms", proc.stdout)
                if match:
                    latency = float(match.group(1))
                    with self._lock:
                        self.samples.append((time.time(), latency))
                        self._update_probes()
                    if self.on_sample:
                        self.on_sample(time.time(), latency)
                else:
                    with self._lock:
                        self.samples.append((time.time(), -1.0))
                        self._update_probes()
                    if self.on_event:
                        self._event(
                            "warning",
                            f"Ping to {self.target}: timeout"
                        )
            except (subprocess.TimeoutExpired, OSError) as exc:
                with self._lock:
                    self.samples.append((time.time(), -1.0))
                    self._update_probes()
            count += 1
            elapsed = time.time() - start
            sleep_time = max(0.1, self.interval - elapsed)
            self._stop.wait(sleep_time)

    def _update_probes(self):
        valid = [s for s in self.samples if s[1] >= 0]
        total = len(self.samples)
        lost = total - len(valid)
        probes = HopProbes(
            sent=total,
            received=len(valid),
            lost=lost,
            packet_loss_pct=(lost / total * 100) if total > 0 else 0.0,
        )
        if valid:
            lats = [s[1] for s in valid]
            probes.min_latency = min(lats)
            probes.max_latency = max(lats)
            probes.avg_latency = sum(lats) / len(lats)
            if len(lats) >= 2:
                diffs = [abs(lats[i] - lats[i - 1]) for i in range(1, len(lats))]
                probes.jitter = sum(diffs) / len(diffs)
            probes.latency_samples = lats
        self.current_probes = probes

    def _event(self, level: str, message: str):
        if self.on_event:
            self.on_event(RouteEvent(
                timestamp=time.time(),
                level=level,
                message=message,
            ))

    def get_stats(self) -> HopProbes:
        with self._lock:
            return self.current_probes

    def get_samples(self) -> list[tuple[float, float]]:
        with self._lock:
            return list(self.samples)

    def get_window(self, seconds: float = 60.0) -> list[tuple[float, float]]:
        cutoff = time.time() - seconds
        with self._lock:
            return [(t, v) for t, v in self.samples if t >= cutoff]
