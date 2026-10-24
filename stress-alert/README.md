# stress-alert

Breath-hold stress dashboard for research use. Open-Motion on the forehead gives blood flow and optical heart rate. A Mentalab ECG on the chest gives ground-truth heart rate. Protocol: 60 s baseline, then a 20 to 40 s breath hold, then 90 s recovery.

## Run the dashboard

```bash
uv sync --locked
uv run python -m dashboard --dev-feed
```

Open http://127.0.0.1:8765. `--dev-feed` replays `data/sample_scan.csv` so the charts move without hardware. Without it, the dashboard waits for producers on `/ws/ingest`.

From any working directory: `.venv/bin/python serve.py --dev-feed`.

## Lanes

| Lane | Paths | Owner |
| :- | :- | :- |
| Dashboard, session/phase logger | `dashboard/`, `session/` | Jahlon |
| Ingest, features, sync | `ingest/`, `features/`, `sync/` | Teammates |

Producers talk to the dashboard only through the message contract in [dashboard/SCHEMA.md](dashboard/SCHEMA.md).

## Status

| Milestone | State |
| :- | :- |
| 1. Server, hub, ingest and browser sockets, live BFI charts from replay | Done |
| 2. Session/phase logger: session bar, phase buttons and timer, `events.csv`, chart shading, LSL markers | Done |
| 3. Contact quality, dual heart rate, stress and alert panels | Planned |

## Versions

Python 3.12, exact pins in `pyproject.toml`, locked in `uv.lock`: fastapi 0.143.0, uvicorn 0.54.0, websockets 17.2, pylsl 1.18.5 (bundles liblsl 1.18). Dev: pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1, ruff 0.17.0. Vendored: uPlot 1.6.32 (MIT, `dashboard/static/vendor/`).

The Mentalab ECG runs in its own environment (`explorepy==4.5.1`, `explorepy push2lsl`) because explorepy hard-pins old numpy, scipy, and pylsl.

## Checks

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Data

`data/sample_scan.csv` is copied from Openwater's [openmotion-bloodflow-app](https://github.com/OpenwaterHealth/openmotion-bloodflow-app) (`resources/sample_scan.csv` at 0be3e90, Apache-2.0): 30 s, 16 cameras, 40 Hz, corrected BFI/BVI. Recordings of team members go in `sessions/`, which is gitignored.
