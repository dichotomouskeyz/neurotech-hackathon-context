"""Development-only producer: replays an Open-Motion corrected CSV into /ws/ingest.

Stands in for the ingest lane until real producers connect. Loops the file forever
and stamps frames with the host's monotonic clock so they share the dashboard's
time base. Run standalone with ``uv run python -m dashboard.dev_feed``.
"""

import asyncio
import csv
import json
import time
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

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


def frames_for(row: dict[str, str], t: float) -> list[dict]:
    return [
        {
            "type": metric,
            "t": t,
            "left": _cameras(row, metric, "l"),
            "right": _cameras(row, metric, "r"),
        }
        for metric in ("bfi", "bvi")
    ]


async def run(url: str, path: Path = DEFAULT_CSV) -> None:
    rows = load_rows(path)
    period = 1.0 / RATE_HZ
    async with connect(f"{url}?source=dev_feed") as ws:
        index = 0
        next_send = time.monotonic()
        while True:
            batch = []
            for _ in range(BATCH):
                t = time.monotonic()
                batch.extend(frames_for(rows[index % len(rows)], t))
                index += 1
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
