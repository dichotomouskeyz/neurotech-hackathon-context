"""Run the dashboard: ``uv run python -m dashboard [--port 8765] [--dev-feed]``.

``--dev-feed`` turns Demo Mode on at startup. The button does the same replay.
"""

import argparse

import uvicorn

from dashboard.app import create_app

parser = argparse.ArgumentParser(prog="python -m dashboard")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument(
    "--dev-feed",
    action="store_true",
    help="start Demo Mode on launch (replay data/sample_scan.csv, 16-channel BFI/BVI)",
)
args = parser.parse_args()

uvicorn.run(create_app(dev_feed=args.dev_feed), host=args.host, port=args.port)
