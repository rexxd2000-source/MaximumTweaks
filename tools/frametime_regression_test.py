"""Regression detector for frame-time captures (Fortnite 500->60->500 workflow).

Detects an FPS/frame-time collapse using RELATIVE thresholds only - nothing is
hardcoded to a specific FPS. Compares a 'compare' run against a 'baseline' run.

Supported inputs (auto-detected by header):
  - CapFrameX export CSV (columns: CaptureTime, frameTimes, ...)
  - PresentMon/RivaTuner CSV (column: msBetweenPresents)
  - plain CSV:  time, frametime_ms
  - plain column of milliseconds

Exit code 1 when a regression is detected, 0 otherwise, so the harness can gate.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HITCH_FIELDS = ("msbetweenpresents", "frametimes", "frametime_ms", "frametime")


def _read_frametimes(path: Path) -> list[float]:
    raw: list[float] = []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        first = sample.lstrip()
        if first.startswith(("{", "[")):
            raise ValueError("JSON captures not supported - export CSV from CapFrameX")
        try:
            reader = csv.reader(fh)
            header = next(reader, None)
        except Exception:
            header = None
        if header is None:
            raise ValueError(f"empty file: {path}")
        low = [c.strip().lower() for c in header]
        col = None
        for i, name in enumerate(low):
            for f in HITCH_FIELDS:
                if f in name:
                    col = i
                    break
            if col is not None:
                break
        if col is None and len(low) == 1:
            col = 0
        if col is None:
            raise ValueError(
                f"no frame-time column in header {header!r} "
                "(expected msBetweenPresents / frameTimes / frametime_ms)")
        for row in reader:
            if not row or len(row) <= col:
                continue
            cell = row[col].strip()
            if not cell:
                continue
            try:
                value = float(cell)
            except ValueError:
                continue
            if value <= 0:
                continue
            raw.append(value)
    if len(raw) < 50:
        raise ValueError(f"only {len(raw)} frames in {path} - need at least 50")
    return raw


def _stats(ft: list[float]) -> dict:
    n = len(ft)
    mean = sum(ft) / n
    srt = sorted(ft)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    fps = [1000.0 / v for v in ft]
    fps_srt = sorted(fps)
    fps_mean = sum(fps) / n
    p1 = fps_srt[max(0, int(n * 0.01) - 1)]
    p01 = fps_srt[max(0, int(n * 0.001) - 1)]
    hitches = sum(1 for v in ft if v > med * 2.0)
    return {
        "frames": n,
        "mean_fps": fps_mean,
        "p1_fps": p1,
        "p01_fps": p01,
        "median_ms": med,
        "max_ms": max(ft),
        "hitch_ratio": hitches / n,
    }


def _collapses(ft: list[float], window: int, drop_ratio: float) -> list[dict]:
    n = len(ft)
    if n < window:
        return []
    fps = [1000.0 / v for v in ft]
    overall = sum(fps) / n
    threshold = overall * (1.0 - drop_ratio)
    cur = sum(fps[:window])
    events: list[dict] = []
    for start in range(0, n - window + 1):
        if start > 0:
            cur += fps[start + window - 1] - fps[start - 1]
        mean = cur / window
        if mean < threshold:
            events.append({"start_frame": start, "end_frame": start + window - 1,
                           "window_mean_fps": mean, "overall_mean_fps": overall})
    merged: list[dict] = []
    for ev in events:
        if merged and ev["start_frame"] <= merged[-1]["end_frame"] + 1:
            merged[-1]["end_frame"] = ev["end_frame"]
            merged[-1]["window_mean_fps"] = min(merged[-1]["window_mean_fps"],
                                                ev["window_mean_fps"])
        else:
            merged.append(dict(ev))
    return merged


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", required=True, type=Path, help="clean/vanilla capture CSV")
    ap.add_argument("--compare", required=True, type=Path, help="with-tweak capture CSV")
    ap.add_argument("--mean-drop", type=float, default=0.25,
                    help="relative mean-FPS drop that flags a regression (default 0.25 = 25%%)")
    ap.add_argument("--hitch-ratio", type=float, default=0.05,
                    help="max allowed fraction of frames above 2x median (default 0.05)")
    ap.add_argument("--window", type=int, default=120,
                    help="frames per sliding measurement window (default 120)")
    ap.add_argument("--json", type=Path, default=None, help="write machine-readable summary")
    args = ap.parse_args(argv)

    base = _read_frametimes(args.baseline)
    comp = _read_frametimes(args.compare)

    sb = _stats(base)
    sc = _stats(comp)

    drop = (sb["mean_fps"] - sc["mean_fps"]) / sb["mean_fps"]
    collapses = _collapses(comp, args.window, args.mean_drop)
    regression = (
        drop > args.mean_drop
        or sc["hitch_ratio"] > args.hitch_ratio
        or len(collapses) > 0
    )

    print(f"\nbaseline : {args.baseline}  frames={sb['frames']}")
    print(f"compare  : {args.compare}   frames={sc['frames']}")
    print()
    print(f"            baseline        compare")
    print(f"mean fps    {sb['mean_fps']:8.1f}      {sc['mean_fps']:8.1f}")
    print(f"1% low      {sb['p1_fps']:8.1f}      {sc['p1_fps']:8.1f}")
    print(f"0.1% low    {sb['p01_fps']:8.1f}      {sc['p01_fps']:8.1f}")
    print(f"max (ms)    {sb['max_ms']:8.2f}      {sc['max_ms']:8.2f}")
    print(f"hitch ratio {sb['hitch_ratio']:8.3f}      {sc['hitch_ratio']:8.3f}")
    print()
    print(f"mean-FPS delta : {drop:+.1%}  (threshold {args.mean_drop:+.0%})")
    print(f"collapse windows detected: {len(collapses)}")
    for c in collapses[:10]:
        print(f"   frames {c['start_frame']:>6}..{c['end_frame']:<6} "
              f"mean {c['window_mean_fps']:6.1f} fps vs overall {c['overall_mean_fps']:6.1f} fps")
    if len(collapses) > 10:
        print(f"   ... and {len(collapses) - 10} more")
    print()
    print("VERDICT: REGRESSION" if regression else "VERDICT: OK")
    if args.json:
        payload = {"baseline": sb, "compare": sc, "mean_drop": drop, "regression": regression,
                   "collapses": collapses}
        args.json.write_text(json.dumps(payload, indent=2))
        print(f"JSON summary: {args.json}")
    return 1 if regression else 0


if __name__ == "__main__":
    sys.exit(main())