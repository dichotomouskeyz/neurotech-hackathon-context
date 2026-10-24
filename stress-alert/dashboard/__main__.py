"""Run the dashboard: ``uv run python -m dashboard [--host 127.0.0.1] [--port 8765]``."""

import argparse

import uvicorn

from dashboard.app import create_app

parser = argparse.ArgumentParser(prog="python -m dashboard")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()

uvicorn.run(create_app(), host=args.host, port=args.port)
