# stress-alert

Breath-hold stress dashboard for research use. Open-Motion on the forehead gives blood flow, blood volume, and optical heart rate. The Mentalab ECG was dropped on 2026-10-24 because it did not work; its code is in git history. Protocol: 60 s baseline, then a 20 to 40 s breath hold, then 90 s recovery.

For research. These numbers are not a diagnosis, a screening result, or a treatment signal. Organizers told the team that human recordings are allowed. Do not change safety-critical optical output or laser parameters. The only path in this package that turns the laser on is the dashboard's **Start scan** button, which runs the SDK's standard scan.

## Run the dashboard

```bash
uv sync --locked
uv run python -m dashboard --dev-feed
```

Open http://127.0.0.1:8765. `--dev-feed` replays `data/sample_scan.csv` so the charts move without hardware. Without it, the dashboard waits for producers on `/ws/ingest`.

Session replay (Operator view) lists corrected scan CSVs under `sessions/` (including `sessions/device-scans/` and `sessions/<id>/scan.csv`) and `data/`. If the recording menu says to restart, the process was started before that route existed: stop it and run `uv run python -m dashboard` again, then hard-refresh the page.

```
ws://<dashboard-host>:8765/ws/ingest?source=<your-name>
```

Every frame field `t` is seconds on `pylsl.local_clock()` of the machine running the dashboard. `GET /api/clock` returns the current value. The readable contract is [dashboard/SCHEMA.md](dashboard/SCHEMA.md). The checker is `dashboard/schema.py`.

Two views, switched in the top bar or with `?view=present`:

- **Operator**: status strip, session and timed-protocol controls, and two charts, blood flow index (BFI) and blood volume index (BVI). Each has its own scale, and they share the time axis, phase bands, and a synced crosshair. The BFI line is the raw pulse. Its vertical scale follows the heartbeat's recent level, the last 8 seconds, with room for the pulse, so a band near 5 to 7 can move to 6 to 8. BVI keeps its own scale. Optical heart rate still uses the raw flow pulse. An optional camera-spread band shows the middle 50% of cameras. While that band is on, the BFI scale includes it.
- **Present**: for the demo screen. Controls are hidden. The pitch (calibrate, then work, then an automatic breath) is on the info control in the header. The top row is phase, heart rate, contact quality, and perfusion. The phase tile reads Calibrate during setup and Work during the bout, and the task line sits on that tile. The circle holds full during an optional calibration breath-hold. When the breath coach is on, it guides a 4 second inhale and a 6 second exhale. Below that row, the heatmap is on the left and the BFI and BVI charts are stacked on the right.

The look is a light, clinical base: flat surfaces, hairline borders, mono numerals. Dark tokens remain in `styles.css` but are off (`data-theme="light"` on `<html>`).

From any working directory: `.venv/bin/python serve.py --dev-feed`.

## Connect the Open-Motion device

The demo runs on a MacBook with the Open-Motion console plugged in over USB.

1. One-time setup on that Mac: `brew install libusb`, then `uv sync --locked` (installs `openmotion-sdk==1.12.0`, the version Openwater's bloodflow app uses). Use Openwater's USB cable only (part 100-00049).
2. Power the console, connect both sensor modules, and start the dashboard.
3. In Operator view, press **Search**. The SDK searches USB and serial. The panel shows console, left sensor, and right sensor, each connected or not found. Hotplug works while connected. The same button reads **Disconnect** once the console is connected, and that releases it.
4. **Start scan** starts the SDK scan with every camera on each connected side and turns the laser on. The button stays disabled until a console and at least one sensor are connected. Live BFI and BVI stream into the charts and the brain heatmap. Contact quality uses per-camera light and dark DN (the same thresholds as `features/cq_score.py`). A covered or unlit camera scores 0. The pipeline timestamp flag is not contact, and a side with no measurement stays null. The same button reads **Stop scan** while a scan is running, and that ends it. Scan CSVs go to `sessions/device-scans/`, which is gitignored.
5. **Demo Mode** is the short offline fallback, not the pitch. It plays a short calibration (baseline, breath-hold, recovery), then a short work loop, with the laser off. The task stays locked through calibration. Work starts with forehead BFI up. The gate locks on that rise immediately. The breath coach runs once the rise has held, then the step unlocks when the average flow is back, eases or asks for a break if blood volume is still up, then locks again when the script drops contact quality. Demo contact scores stay below 1.00 (for example 0.82, then 0.78, then 0.32). Demo Mode refuses to start while a live scan is running, so it cannot overwrite headset contact. The button is on the operator bar. It reads **Stop Demo** while the script is running.
6. **Run timed** is the live path. It starts a session if you have not, then runs the durations on the card. Defaults are a 20 second baseline sit, hold at 0 (the breath-hold and its recovery are skipped), then work for 20 minutes (1200 s). Type a hold above 0 to include the breath-hold as calibration proof, and a recovery window after it. Work then runs for the Work field, 20 minutes by default. While it is running the same button reads **Stop protocol**. During baseline each camera stores its own median, and only while contact quality is at least 0.50. The recovery gate stays shut through calibration. During work it opens only when forehead BFI is back within the operator boundary (default 5% of that baseline, allowed 1% to 25% on the timed-protocol card) and contact quality is still at least 0.50. The boundary is applied when Run timed or Demo Mode starts, and it stays fixed until the next start. While work is running, the gate locks as soon as BFI crosses that boundary. The breath coach does not. It starts when a 4 second trailing mean of the BFI rise is still over the boundary and at least three quarters of that window is too. It stays on until the mean is under half the boundary. A one- or two-second blip locks the gate and does not start the breath. One quiet sample opens the gate again and does not cancel the breath. You do not wait for the bout to end. Recovery τ is the fitted decay time constant from a hold, when one was run. It is not on the dashboard, and it is not the phase countdown. A tau of 18 s or slower also coaches a breath and eases the step. Bad contact keeps the gate locked and does not start a breath. When the gate opens, task difficulty advances. If blood volume is still high, the step eases or the banner asks for a break. The perfusion tile is the larger of the BFI and BVI rises on the responsive cameras. It is secondary. It does not unlock the task, and it is not a stressed-or-not score. Optical heart rate is estimated from the BFI pulse for the side panel. It is not an input. If a hold is used and never stays elevated, recovery is about 4 s, the cue says why, and the work step does not pretend to unlock. Switch to **Present** for the judge view. For research. Not a diagnosis.

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
| 3. Contact quality, optical heart rate, perfusion tile, recovery gate | Done on the live scan, on Demo Mode, and on `--dev-feed`. Calibration learns resting BFI. The work step unlocks when forehead BFI has returned and contact quality is at least 0.50. The perfusion tile is secondary. Optical heart rate is a side panel, on the live scan and `--dev-feed` only, because the Demo Mode script has no pulse |

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
| Demo script (calibrate, long work, auto breath) | [docs/DEMO_SCRIPT_60S.md](docs/DEMO_SCRIPT_60S.md) |
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
