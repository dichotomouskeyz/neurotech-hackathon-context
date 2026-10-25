"""List recorded Open-Motion scan CSVs and seek to a time through the live hub path."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dashboard import clock, dev_feed
from dashboard.live_gate import LiveGate

WINDOW_S = 30.0
SCAN_MARKERS = ("timestamp_s", "bfi_l1")


def is_scan_csv(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".csv":
        return False
    try:
        with path.open(newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
    except OSError:
        return False
    if not header:
        return False
    return all(marker in header for marker in SCAN_MARKERS)


def _session_label(directory: Path) -> str | None:
    meta = directory / "meta.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    sid = data.get("session_id") or directory.name
    subject = data.get("subject_id")
    if subject:
        return f"{sid} ({subject})"
    return str(sid)


def list_recordings(*roots: Path) -> list[dict[str, Any]]:
    """Scan CSV files under ``roots``, newest first."""
    seen: dict[str, dict[str, Any]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.csv")):
            if not is_scan_csv(path):
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            rows = dev_feed.load_rows(path)
            if not rows:
                continue
            try:
                duration_s = float(rows[-1]["timestamp_s"])
            except (KeyError, TypeError, ValueError):
                continue
            label = path.name
            session_dir = path.parent if (path.parent / "meta.json").is_file() else None
            if session_dir is not None:
                session_label = _session_label(session_dir)
                if session_label:
                    label = session_label
            seen[key] = {
                "id": key,
                "path": key,
                "label": label,
                "duration_s": duration_s,
                "frames": len(rows),
            }
    return sorted(seen.values(), key=lambda item: item["path"], reverse=True)


@dataclass
class LoadedRecording:
    path: Path
    rows: list[dict[str, str]]
    duration_s: float


class ReplayEngine:
    """Load a corrected scan CSV and publish hub frames for a seek time."""

    def __init__(self) -> None:
        self.loaded: LoadedRecording | None = None
        self.active = False
        self.position_s = 0.0

    def load(self, path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        if not is_scan_csv(resolved):
            raise ValueError(f"not a corrected Open-Motion scan CSV: {resolved}")
        rows = dev_feed.load_rows(resolved)
        if not rows:
            raise ValueError(f"scan CSV is empty: {resolved}")
        duration_s = float(rows[-1]["timestamp_s"])
        self.loaded = LoadedRecording(resolved, rows, duration_s)
        self.active = True
        self.position_s = 0.0
        return {
            "active": True,
            "path": str(resolved),
            "duration_s": duration_s,
            "frames": len(rows),
        }

    def stop(self) -> dict[str, Any]:
        self.loaded = None
        self.active = False
        self.position_s = 0.0
        return {"active": False, "path": None, "duration_s": 0.0, "position_s": 0.0}

    def state(self) -> dict[str, Any]:
        if not self.loaded:
            return {"active": False, "path": None, "duration_s": 0.0, "position_s": 0.0}
        return {
            "active": self.active,
            "path": str(self.loaded.path),
            "duration_s": self.loaded.duration_s,
            "position_s": self.position_s,
        }

    def seek(
        self,
        t_s: float,
        *,
        gate: LiveGate,
        publish: Callable[[list[dict[str, Any]]], None],
    ) -> dict[str, Any]:
        if not self.loaded:
            raise ValueError("load a recording first")
        t_s = max(0.0, min(float(t_s), self.loaded.duration_s))
        self.position_s = t_s
        gate.reset()
        now = clock.now()
        window_start = max(0.0, t_s - WINDOW_S)
        out: list[dict[str, Any]] = []
        for row in self.loaded.rows:
            try:
                ts = float(row["timestamp_s"])
            except (KeyError, TypeError, ValueError):
                continue
            if ts > t_s:
                break
            lsl_t = now - (t_s - ts)
            frames = dev_feed.frames_for(row, lsl_t)
            extras = gate.observe(frames)
            if ts + 1.0 / dev_feed.RATE_HZ >= window_start:
                out.extend(frames)
                out.extend(extras)
        if out:
            publish(out)
        publish(
            [
                {
                    "type": "status",
                    "source": "replay",
                    "connected": True,
                    "detail": f"{self.loaded.path.name} @ {t_s:.2f}s",
                }
            ]
        )
        return {"position_s": t_s, "published_frames": len(out)}


def ensure_session_scan_copy(session_dir: Path, source: Path) -> Path:
    """Write the smallest replay artifact for a session (used after Demo Mode)."""
    session_dir.mkdir(parents=True, exist_ok=True)
    dest = session_dir / "scan.csv"
    if not dest.is_file():
        dest.write_bytes(source.read_bytes())
    meta_path = session_dir / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            meta = {}
    meta["scan_csv"] = "scan.csv"
    meta_path.write_text(json.dumps(meta, indent=2))
    return dest
