"""Run the dashboard: ``uv run python -m dashboard [--port 8765] [--dev-feed]``."""

import argparse

import uvicorn

from dashboard.app import create_app

parser = argparse.ArgumentParser(prog="python -m dashboard")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument(
    "--dev-feed", action="store_true", help="replay data/sample_scan.csv into /ws/ingest"
)
args = parser.parse_args()

feed_url = f"ws://127.0.0.1:{args.port}/ws/ingest" if args.dev_feed else None
uvicorn.run(create_app(dev_feed_url=feed_url), host=args.host, port=args.port)
