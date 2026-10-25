"""Run the dashboard: ``uv run python -m dashboard [--port 8765] [--replay [CSV]]``."""

import argparse
from pathlib import Path

import uvicorn

from dashboard import dev_feed
from dashboard.app import create_app

parser = argparse.ArgumentParser(prog="python -m dashboard")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument(
    "--replay",
    nargs="?",
    const=str(dev_feed.DEFAULT_CSV),
    metavar="CSV",
    help="replay a recorded corrected scan CSV into /ws/ingest (default: data/sample_scan.csv)",
)
parser.add_argument(
    "--dev-feed", action="store_true", help="alias for --replay with the default CSV"
)
args = parser.parse_args()

replay_csv = args.replay or (str(dev_feed.DEFAULT_CSV) if args.dev_feed else None)
replay_url = f"ws://127.0.0.1:{args.port}/ws/ingest" if replay_csv else None
app = create_app(
    replay_url=replay_url,
    replay_csv=Path(replay_csv) if replay_csv else None,
)
uvicorn.run(app, host=args.host, port=args.port)
