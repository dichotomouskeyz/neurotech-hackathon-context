"""List recorded Open-Motion scan CSVs and seek to a time through the live hub path."""

from __future__ import annotations

import csv
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dashboard import clock, dev_feed
from dashboard.live_gate import LiveGate

WINDOW_S = 30.0
SCAN_MARKERS = ("timestamp_s", "bfi_l1")
# Header probe and the last data row. Listing must not read a whole scan.
_HEADER_BYTES = 8192
_TAIL_BYTES = 65536


def _header_fields(path: Path) -> list[str] | None:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(_HEADER_BYTES)
    except OSError:
        return None
    line = chunk.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip("\r\ufeff")
    if not line:
        return None
    fields = next(csv.reader([line]), None)
    if not fields:
        return None
    return [field.strip().lstrip("\ufeff") for field in fields]


def is_scan_csv(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".csv":
        return False
    header = _header_fields(path)
    if not header:
        return False
    return all(marker in header for marker in SCAN_MARKERS)


def _last_timestamp_s(path: Path) -> float | None:
    """Last ``timestamp_s`` from the end of the file. Does not read the whole scan."""
    header = _header_fields(path)
    if not header or "timestamp_s" not in header:
        return None
    index = header.index("timestamp_s")
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - _TAIL_BYTES))
            chunk = handle.read()
    except OSError:
        return None
    text = chunk.decode("utf-8", errors="replace")
    lines = [line.strip("\r") for line in text.splitlines() if line.strip()]
    # A mid-file seek starts on a partial row.
    if size > _TAIL_BYTES and lines:
        lines = lines[1:]
    for line in reversed(lines):
        parts = next(csv.reader([line]), None)
        if not parts or len(parts) <= index:
            continue
        try:
            return float(parts[index])
        except ValueError:
            continue
    return None


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


def _describe(path: Path) -> dict[str, Any]:
    """One catalog row. Header match is enough; duration is best-effort."""
    label = path.name
    session_dir = path.parent if (path.parent / "meta.json").is_file() else None
    if session_dir is not None:
        session_label = _session_label(session_dir)
        if session_label:
            label = f"{session_label} — {path.name}"
    try:
        duration_s = _last_timestamp_s(path)
    except OSError:
        duration_s = None
    resolved = str(path.resolve())
    return {
        "id": resolved,
        "path": resolved,
        "label": label,
        "duration_s": duration_s,
        "frames": None,
    }


def list_recordings(*roots: Path) -> list[dict[str, Any]]:
    """Corrected scan CSVs under ``roots``, newest path first.

    A session folder that only has ``meta.json`` and ``events.csv`` is not a
    recording. ``events.csv`` fails the scan header check and is skipped.
    One bad file does not drop the rest of the catalog.
    """
    seen: dict[str, dict[str, Any]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            paths = sorted(root.rglob("*.csv"))
        except OSError:
            continue
        for path in paths:
            try:
                if not is_scan_csv(path):
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                seen[key] = _describe(path)
            except OSError:
                continue
    return sorted(seen.values(), key=lambda item: item["path"], reverse=True)


def newest_scan_csv(directory: Path, since: float | None = None) -> Path | None:
    """Newest corrected scan CSV in ``directory`` (not nested), optionally after ``since``."""
    if not directory.is_dir():
        return None
    best: tuple[float, Path] | None = None
    try:
        paths = list(directory.glob("*.csv"))
    except OSError:
        return None
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if since is not None and mtime < since:
            continue
        if not is_scan_csv(path):
            continue
        if best is None or mtime >= best[0]:
            best = (mtime, path)
    return None if best is None else best[1]


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
    """Link or copy a playable scan into the session folder.

    Hard link when the scan already sits on the same volume (live SDK output
    under ``sessions/device-scans``). Copy when a link is not possible.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    dest = session_dir / "scan.csv"
    source = source.resolve()
    if not dest.exists():
        try:
            os.link(source, dest)
        except OSError:
            shutil.copyfile(source, dest)
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
