# stress-alert

Breath-hold stress dashboard for research use. Open-Motion on the forehead gives blood flow, blood volume, and optical heart rate. The Mentalab ECG was dropped on 2026-10-24 because it did not work; its code is in git history. Protocol: 60 s baseline, then a 20 to 40 s breath hold, then 90 s recovery.

For research. These numbers are not a diagnosis, a screening result, or a treatment signal. Organizers told the team that human recordings are allowed. Do not change safety-critical optical output or laser parameters. The only path in this package that turns the laser on is the dashboard's **Start scan (laser on)** button, which runs the SDK's standard scan.

## Run the dashboard

```bash
uv sync --locked
uv run python -m dashboard --dev-feed
```

Open http://127.0.0.1:8765. `--dev-feed` replays `data/sample_scan.csv` so the charts move without hardware. Without it, the dashboard waits for producers on `/ws/ingest`.

```
ws://<dashboard-host>:8765/ws/ingest?source=<your-name>
```

Every frame field `t` is seconds on `pylsl.local_clock()` of the machine running the dashboard. `GET /api/clock` returns the current value. The readable contract is [dashboard/SCHEMA.md](dashboard/SCHEMA.md). The checker is `dashboard/schema.py`.

Two views, switched in the top bar or with `?view=present`:

- **Operator**: status strip, session and timed-protocol controls, and two charts, blood flow index (BFI) and blood volume index (BVI). Each has its own scale, and they share the time axis, phase bands, and a synced crosshair. The BFI line is a 1 second trailing mean so the heartbeat does not set the vertical scale and the left/right offset stays readable. BVI stays on the raw samples. Optical heart rate still uses the raw flow pulse. An optional camera-spread band shows the middle 50% of cameras, and while that band is on it is included in the scale.
- **Present**: for the demo screen. Controls are hidden. The phase tile reads Calibrate during the breath-hold setup and Work during the application. The circle holds full during the calibration breath-hold and, while the work step is locked or the breath coach is on, guides a 4 second inhale and a 6 second exhale. The recovery gate, contact quality, and the BFI/BVI charts lead. Heart rate and the perfusion percent sit beside them as secondary telemetry.

The look is a light, clinical base: flat surfaces, hairline borders, mono numerals. Dark tokens remain in `styles.css` but are off (`data-theme="light"` on `<html>`).

From any working directory: `.venv/bin/python serve.py --dev-feed`.

## Connect the Open-Motion device

The demo runs on a MacBook with the Open-Motion console plugged in over USB.

1. One-time setup on that Mac: `brew install libusb`, then `uv sync --locked` (installs `openmotion-sdk==1.12.0`, the version Openwater's bloodflow app uses). Use Openwater's USB cable only (part 100-00049).
2. Power the console, connect both sensor modules, and start the dashboard.
3. In Operator view, press **Connect device**. The SDK searches USB and serial. The panel shows console, left sensor, and right sensor, each connected or not found. Hotplug works while connected, and **Search again** re-reads the state.
4. **Start scan (laser on)** starts the SDK scan with every camera on each connected side. Live BFI and BVI stream into the charts and the brain heatmap. Contact quality uses per-camera light and dark DN (the same thresholds as `features/cq_score.py`). A covered or unlit camera scores 0. The pipeline timestamp flag is not contact, and a side with no measurement stays null. **Stop scan** ends it. Scan CSVs go to `sessions/device-scans/`, which is gitignored.
5. **Demo Mode** plays calibration, then work, with the laser off. Calibration is a short baseline, breath-hold, and recovery. The task stays locked. Work starts with forehead BFI up, unlocks when BFI is back toward the calibrated baseline and contact is good, eases or asks for a break if blood volume is still up, then locks again when the script drops contact quality. Demo contact scores stay below 1.00 (for example 0.82, then 0.78, then 0.32). Demo Mode refuses to start while a live scan is running, so it cannot overwrite headset contact. The button is on the operator bar and on the heatmap toolbar. Switch to **Present** for the judge view.
6. **Closed loop (~60s)** is the same two parts on a live scan. It starts a session if you have not, then runs the durations on the card. The defaults are one minute: calibration is baseline 8 s, breath-hold up to 8 s, and recovery up to 12 s, then work for 32 s. A full sitting is still 60 / 30 / 90 if you type those in and set work to match. During baseline each camera stores its own median, and only while contact quality is at least 0.50. The recovery gate stays shut through calibration. It opens during work only when forehead BFI is back under 5% of that baseline and contact quality is still at least 0.50. Recovery τ on the gate card is the fitted decay time constant. It stays blank until that fit succeeds, and it is not the phase countdown. Bad contact keeps it locked. When it opens, task difficulty advances. If blood volume is still high, the step eases or the banner asks for a break. If the recovery time constant is 18 s or slower, the breath coach runs and the step eases. The perfusion tile is the larger of the BFI and BVI rises on the responsive cameras. It is secondary. It does not unlock the task. Optical heart rate is estimated from the BFI pulse for the side panel. It is not an input. If the hold never stays elevated, recovery is about 4 s, the cue says why, and the work step does not pretend to unlock. For research. Not a diagnosis.

Errors name the fix: SDK not installed, libusb missing, no console found, or which sensor is missing. Code: `dashboard/device.py` (`DeviceManager`, plus `LiveSink` on the SDK's `live` channel). API: `GET /api/device`, `POST /api/device/connect`, `/disconnect`, `/scan/start`, `/scan/stop`.

## Lanes

| Lane | Paths | Role |
| :- | :- | :- |
| Dashboard, session/phase logger | `dashboard/`, `session/` | Live UI, hub, phase timer, LSL phase markers |
| Lane 1 Open-Motion | `ingest/omotion_source.py`, `features/cq_score.py`, `features/pulse_hr.py`, `replay_csv.py` | CSV replay, side averages, contact quality, optical heart rate |
| Lane 4 protocol and alert math | `features/stress_index.py`, `features/track3_classifier.py`, `protocol/breathhold.md` | CQ-gated stress index, recovery time constant, breath-hold protocol |

Producers talk to the dashboard only through [dashboard/SCHEMA.md](dashboard/SCHEMA.md). Offline replay CSVs are a separate contract, below. They are not the WebSocket frames.

## Status

| Milestone | State |
| :- | :- |
| 1. Server, hub, ingest and browser sockets, live BFI charts from replay | Done |
| 2. Session/phase logger: session bar, phase buttons and timer, `events.csv`, chart shading, LSL markers | Done |
| 3. Contact quality, optical heart rate, perfusion tile, recovery gate | Done on the live scan, on Demo Mode, and on `--dev-feed`. Calibration learns resting BFI. The work step unlocks when forehead BFI has returned and contact quality is at least 0.50. The perfusion tile is secondary. Optical heart rate is a side panel |

## Versions

Python 3.12, pins in `pyproject.toml`, locked in `uv.lock`. Dashboard: fastapi 0.143.0, uvicorn 0.54.0, websockets 17.2, pylsl 1.18.5 (bundles liblsl 1.18). Replay: numpy, pandas, scipy. Dev: pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1, ruff 0.17.0. Vendored in `dashboard/static/vendor/`: uPlot 1.6.32 (MIT), Geist and Geist Mono variable fonts 5.3.0 from Fontsource (OFL-1.1). Chart and status colors come from the dataviz reference palette. The left/right pair passes its palette validator in light and dark.

## Lane 1 CSV replay

From the repo root, with this directory on `PYTHONPATH` (the replay scripts insert it themselves):

```bash
python stress-alert/replay_csv.py \
  --csv stress-alert/data/synthetic_scan.csv \
  --out stress-alert/data/side_averages.csv
```

`synthetic_scan.csv` is 640 frames at 40 Hz with a 72 bpm pulse on BFI. Camera r8 is marked `nan_filled`. The command prints side-average BFI/BVI, mean CQ, bad-coupling frames, and `optical_hr_bpm` near 72. `data/sample_scan.csv` is the 30 s Openwater example the dashboard dev feed uses. Pass that path the same way.

`--window-s 1` writes a 1 second trailing mean of the side averages. Heart rate still uses the per-frame trace. The default window is 0: one output row per input frame.

`side_averages.csv`:

| Column | Meaning |
| :- | :- |
| `timestamp_s` | Frame time from the scan CSV, seconds |
| `bfi_l`, `bfi_r` | Mean of finite cameras on that side. Blank cells are omitted from the mean |
| `bvi_l`, `bvi_r` | Same for blood volume index |
| `cq` | Mean per-camera quality, 0 to 1. Blank when the scan has no `quality_*` columns |

`bad_coupling` is true when `cq` is strictly below 0.5. The CLI counts those frames. Gate pulse features on that flag. The live `cq` frame in SCHEMA.md is per side (`left`, `right`), each 0 to 1. The live `bfi` and `bvi` frames are 8 cameras per side, not these side means.

`features/pulse_hr.py` detrends BFI and reports the pulse rate between 0.7 and 3.0 Hz (42 to 180 bpm). A stronger half-rate tone does not replace the pulse when the faster peak has its own harmonic. A pulse that really sits near 50 bpm stays near 50 bpm.

- One rate for the whole clip. No beat-to-beat intervals or HRV.
- Not checked against a reference heart rate. Report it as an optical estimate.
- Clips shorter than about 8 seconds return no rate.
- Motion and bad coupling can move the peak. Gate on CQ first.
- Respiration sits near 0.2 Hz and falls outside the search band.
- `hr_confidence` near 1 is a sharp peak. Near 0.5 the band is flat and no rate is printed.

Live scan, only on the station host:

```python
from ingest.omotion_source import start_live_scan

iface = start_live_scan(data_dir="C:/scans", subject_id="phantom-01", allow_live=True)
iface.scan_workflow.await_complete()
iface.stop()
```

`allow_live=False` raises. `demo_mode=True` raises. `MotionInterface(demo_mode=True)` connected nothing and wrote no BFI/BVI frames in the 2026-10-24 Mac check (`docs/OPEN-MOTION.md`). Use a corrected CSV offline.

Contact quality and a hardware scan are demonstrated upstream:

https://github.com/OpenwaterHealth/openmotion-sdk/blob/main/scripts/sdk_examples.py

```bash
python scripts/sdk_examples.py contact-quality
python scripts/sdk_examples.py scan
```

Those examples talk to the console and can turn the laser on. Run them from an `openmotion-sdk` checkout on the Windows host, not from this CLI.

## Lane 4 protocol and stress index

For research. The stress index is not a diagnosis, a screening result, or a treatment signal.

| Piece | Path |
| :- | :- |
| Protocol | [protocol/breathhold.md](protocol/breathhold.md) |
| CQ-gated stress index and recovery tau | [features/stress_index.py](features/stress_index.py) |
| Optional Track 3 classifier | [features/track3_classifier.py](features/track3_classifier.py) |
| 60-second demo script | [docs/DEMO_SCRIPT_60S.md](docs/DEMO_SCRIPT_60S.md) |
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

`data/sample_scan.csv` is copied from Openwater's [openmotion-bloodflow-app](https://github.com/OpenwaterHealth/openmotion-bloodflow-app) (`resources/sample_scan.csv` at 0be3e90, Apache-2.0): 30 s, 16 cameras, 40 Hz, corrected BFI/BVI. `synthetic_scan.csv` is the 72 bpm offline fixture. Recordings of team members go in `sessions/`, which is gitignored. See `data/README.md`.
