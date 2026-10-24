# stress-alert

Breath-hold stress dashboard for research use. Open-Motion on the forehead gives blood flow, blood volume, and optical heart rate. The Mentalab ECG was dropped on 2026-10-24 because it did not work; its code is in git history. Protocol: 60 s baseline, then a 20 to 40 s breath hold, then 90 s recovery.

For research. These numbers are not a diagnosis, a screening result, or a treatment signal. Organizers told the team that human recordings are allowed. Do not change safety-critical optical output or laser parameters. The only path in this package that turns the laser on is the dashboard's **Start scan (laser on)** button, which runs the SDK's standard scan.

## Run the dashboard

```bash
uv sync --locked
uv run python -m dashboard
```

Open http://127.0.0.1:8765. The dashboard shows live data only: from the Open-Motion device (Connect device, below) and from producers on `/ws/ingest`. Replay and synthetic data were removed on 2026-10-24. With no device connected, every panel shows its waiting state.

```
ws://<dashboard-host>:8765/ws/ingest?source=<your-name>
```

Every frame field `t` is seconds on `pylsl.local_clock()` of the machine running the dashboard. `GET /api/clock` returns the current value. The readable contract is [dashboard/SCHEMA.md](dashboard/SCHEMA.md). The checker is `dashboard/schema.py`.

Two views, switched in the top bar or with `?view=present`:

- **Operator**: status strip, session and timed-protocol controls, and two charts, blood flow index (BFI) and blood volume index (BVI). Each has its own scale, and they share the time axis, phase bands, and a synced crosshair. An optional camera-spread band shows the middle 50% of cameras.
- **Present**: for the demo screen. Controls are hidden. The phase becomes a breathing circle that rises and falls gently at baseline, holds full during the breath hold, and moves faster during recovery, ringed by the timed-phase countdown. Heart rate, contact quality and stress sit beside it.

The look is a light, clinical base: flat surfaces, hairline borders, mono numerals. Dark tokens remain in `styles.css` but are off (`data-theme="light"` on `<html>`).

From any working directory: `.venv/bin/python serve.py`.

## Connect the Open-Motion device

The demo runs on a MacBook with the Open-Motion console plugged in over USB.

1. One-time setup on that Mac: `brew install libusb`, then `uv sync --locked` (installs `openmotion-sdk==1.12.0`, the version Openwater's bloodflow app uses). Use Openwater's USB cable only (part 100-00049).
2. Power the console, connect both sensor modules, and start the dashboard.
3. In Operator view, press **Connect device**. The SDK searches USB and serial. The panel shows console, left sensor, and right sensor, each connected or not found. Hotplug works while connected, and **Search again** re-reads the state.
4. **Start scan (laser on)** starts the SDK scan with every camera on each connected side. Live BFI and BVI stream into the charts. **Stop scan** ends it. Scan CSVs go to `sessions/device-scans/`, which is gitignored.

Errors name the fix: SDK not installed, libusb missing, no console found, or which sensor is missing. Code: `dashboard/device.py` (`DeviceManager`, plus `LiveSink` on the SDK's `live` channel). API: `GET /api/device`, `POST /api/device/connect`, `/disconnect`, `/scan/start`, `/scan/stop`.

## Lanes

| Lane | Paths | Role |
| :- | :- | :- |
| Dashboard, session/phase logger | `dashboard/`, `session/` | Live UI, hub, phase timer, LSL phase markers |
| Lane 1 Open-Motion | `ingest/omotion_source.py`, `features/cq_score.py`, `features/pulse_hr.py` | Gated scripted live scan, contact quality, optical heart rate |
| Lane 4 protocol and alert math | `features/stress_index.py`, `features/track3_classifier.py`, `protocol/breathhold.md` | CQ-gated stress index, recovery time constant, breath-hold protocol |

Producers talk to the dashboard only through [dashboard/SCHEMA.md](dashboard/SCHEMA.md).

## Status

| Milestone | State |
| :- | :- |
| 1. Server, hub, ingest and browser sockets, live BFI and BVI charts | Done |
| 2. Session/phase logger: session bar, phase buttons and timer, `events.csv`, chart shading, LSL markers | Done |
| 3. Contact quality, optical heart rate, stress and alert panels | Panels done. CQ, optical heart rate, and the CQ-gated stress index exist as features; live producers that send them to the dashboard are still to do |

## Versions

Python 3.12, pins in `pyproject.toml`, locked in `uv.lock`. Dashboard: fastapi 0.143.0, uvicorn 0.54.0, websockets 17.2, pylsl 1.18.5 (bundles liblsl 1.18). Device: openmotion-sdk 1.12.0. Optical heart rate: numpy, scipy. Dev: pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1, ruff 0.17.0. Vendored in `dashboard/static/vendor/`: uPlot 1.6.32 (MIT), Geist and Geist Mono variable fonts 5.3.0 from Fontsource (OFL-1.1). Chart and status colors come from the dataviz reference palette. The left/right pair passes its palette validator in light and dark.

## Lane 1 features

`features/cq_score.py` scores contact quality from per-camera labels or DN readings, 0 to 1. `bad_coupling` is true when the score is strictly below 0.5. The live `cq` frame in SCHEMA.md is per side (`left`, `right`), each 0 to 1.

`features/pulse_hr.py` detrends BFI and reports the strongest frequency between 0.7 and 3.0 Hz (42 to 180 bpm).

- One rate for the whole window. No beat-to-beat intervals or HRV.
- Not checked against a reference heart rate. Report it as an optical estimate.
- Windows shorter than about 8 seconds return no rate.
- Motion and bad coupling can move the peak. Gate on CQ first.
- Respiration sits near 0.2 Hz and falls outside the search band.
- `hr_confidence` near 1 is a sharp peak. Near 0.5 the band is flat and no rate is reported.

Scripted live scan (the dashboard's Connect device button is the usual path):

```python
from ingest.omotion_source import start_live_scan

iface = start_live_scan(data_dir="sessions/device-scans", subject_id="phantom-01", allow_live=True)
iface.scan_workflow.await_complete()
iface.stop()
```

`allow_live=False` raises. `demo_mode=True` raises: `MotionInterface(demo_mode=True)` connected nothing and wrote no BFI/BVI frames in the 2026-10-24 Mac check (`docs/OPEN-MOTION.md`).

## Lane 4 protocol and stress index

For research. The stress index is not a diagnosis, a screening result, or a treatment signal.

| Piece | Path |
| :- | :- |
| Protocol | [protocol/breathhold.md](protocol/breathhold.md) |
| CQ-gated stress index and recovery tau | [features/stress_index.py](features/stress_index.py) |
| Optional Track 3 classifier | [features/track3_classifier.py](features/track3_classifier.py) |
| 60-second demo script | [../docs/DEMO_SCRIPT_60S.md](../docs/DEMO_SCRIPT_60S.md) |
| Devpost draft | [../docs/DEVPOST_DRAFT.md](../docs/DEVPOST_DRAFT.md) |
| Unit tests | [tests/test_stress_index.py](tests/test_stress_index.py) |

The same Lane 4 files are mirrored at the repo root (`features/`, `protocol/`, `tests/test_stress_index.py`, `docs/`) so `python3 -m unittest tests/test_stress_index.py` works from the repository root. Imports inside `stress-alert/` use this directory's `features` package.

`compute_stress_frame` returns a `stress` frame for [dashboard/SCHEMA.md](dashboard/SCHEMA.md). `t` is `pylsl.local_clock()` on the dashboard machine. `alert` is forced false when contact quality is missing or below 0.50.

```python
from features.stress_index import StressTracker, compute_stress_frame

result = compute_stress_frame(
    t=1089839.91,
    current_value=2.70,
    baseline_value=2.00,
    cq=0.88,
)
frame = result.to_frame()

tracker = StressTracker()
tracker.on_phase("baseline", t=0.0)
tracker.on_sample(t=1.0, value=2.0, cq=0.9)
```

`StressTracker` takes the median of clean baseline samples, then scores hold and recovery against that baseline. `compute_recovery_tau` fits an exponential time constant on the recovery window. A short or flat window returns an honest null (`ok` false) instead of a tau. `features/track3_classifier.py` is optional and stays unused unless ingest is verified.

## Checks

Lane 4, from the repo root (standard library only):

```bash
python3 -m unittest tests/test_stress_index.py
```

Lane 1, Lane 4, and the dashboard tests, from the repo root, using the project environment (`uv sync` installs pytest, which the dashboard tests import):

```bash
stress-alert/.venv/bin/python -m unittest discover -s stress-alert/tests -t stress-alert
```

Dashboard, from `stress-alert/`:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Data

No sample, replay, or synthetic data ships with the app. Live recordings go in `sessions/` (phase events) and `sessions/device-scans/` (SDK scan CSVs), which are gitignored and stay on the machine.
