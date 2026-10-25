"""16-channel sample replay used by Demo Mode and ``--dev-feed``.

Loops ``data/sample_scan.csv`` and stamps frames with the shared clock
(``dashboard.clock``). The dashboard plays it in-process. The standalone module
still pushes the same batches to ``/ws/ingest``:

``uv run python -m dashboard.dev_feed``
"""

import asyncio
import csv
import json
import time
from collections.abc import Callable
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from dashboard import clock
from features.cq_score import cq_score

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "sample_scan.csv"
RATE_HZ = 40.0
BATCH = 4  # frames per message, so 10 messages per second at 40 Hz


def _cameras(row: dict[str, str], metric: str, side: str) -> list[float | None]:
    values = []
    for cam in range(1, 9):
        raw = row.get(f"{metric}_{side}{cam}", "")
        values.append(float(raw) if raw not in ("", "nan") else None)
    return values


def load_rows(path: Path = DEFAULT_CSV) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _side_cq(row: dict[str, str], side: str) -> float | None:
    labels = []
    for cam in range(1, 9):
        raw = row.get(f"quality_{side}{cam}", "")
        text = "" if raw is None else str(raw).strip()
        if text and text.lower() != "nan":
            labels.append(text)
    if not labels:
        return None
    try:
        return cq_score(labels).score
    except (TypeError, ValueError):
        return None


def frames_for(row: dict[str, str], t: float) -> list[dict]:
    frames = [
        {
            "type": metric,
            "t": t,
            "left": _cameras(row, metric, "l"),
            "right": _cameras(row, metric, "r"),
        }
        for metric in ("bfi", "bvi")
    ]
    left, right = _side_cq(row, "l"), _side_cq(row, "r")
    if left is None and right is None:
        return frames
    # A side with no quality labels is missing, not a perfect score.
    frames.append({"type": "cq", "t": t, "left": left, "right": right})
    return frames


def take_batch(rows: list[dict[str, str]], index: int) -> tuple[list[dict], int]:
    """Next ``BATCH`` rows as ingest frames, each stamped with ``clock.now``."""
    batch: list[dict] = []
    for _ in range(BATCH):
        batch.extend(frames_for(rows[index % len(rows)], clock.now()))
        index += 1
    return batch, index


async def replay(
    publish: Callable[[list[dict]], None],
    path: Path = DEFAULT_CSV,
    *,
    scanning: Callable[[], bool] | None = None,
) -> str:
    """Publish the sample scan until cancelled or a live scan starts.

    Returns ``"scan"`` when ``scanning`` becomes true, before the next batch.
    Cancellation propagates. This is the playback Demo Mode and ``--dev-feed`` share.
    """
    rows = load_rows(path)
    if not rows:
        raise ValueError(f"no rows in {path}")
    period = 1.0 / RATE_HZ
    index = 0
    next_send = time.monotonic()
    while True:
        if scanning is not None and scanning():
            return "scan"
        batch, index = take_batch(rows, index)
        publish(batch)
        next_send += period * BATCH
        await asyncio.sleep(max(0.0, next_send - time.monotonic()))


async def run(url: str, path: Path = DEFAULT_CSV) -> None:
    rows = load_rows(path)
    period = 1.0 / RATE_HZ
    async with connect(f"{url}?source=dev_feed") as ws:
        index = 0
        next_send = time.monotonic()
        while True:
            batch, index = take_batch(rows, index)
            await ws.send(json.dumps(batch))
            next_send += period * BATCH
            await asyncio.sleep(max(0.0, next_send - time.monotonic()))


async def run_forever(url: str, path: Path = DEFAULT_CSV, retry_s: float = 1.0) -> None:
    """Keep replaying, reconnecting if the dashboard restarts."""
    while True:
        try:
            await run(url, path)
        except (OSError, WebSocketException) as exc:
            print(f"dev_feed: {exc}; retrying in {retry_s}s")
        await asyncio.sleep(retry_s)


if __name__ == "__main__":
    asyncio.run(run_forever("ws://127.0.0.1:8765/ws/ingest"))
