# stress-alert

Breath-hold stress dashboard for research use. Open-Motion on the forehead gives blood flow and optical heart rate. A Mentalab ECG on the chest gives an ECG heart rate and a short HRV set (RMSSD, SDNN) for the research cross-check. Protocol: 60 s baseline, then a 20 to 40 s breath hold, then 90 s recovery.

For research. These numbers are not a diagnosis, a screening result, or a treatment signal. Organizers told the team that human recordings are allowed. Do not change safety-critical optical output, and do not enable the laser from this package.

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

- **Operator**: status strip, session and timed-protocol controls, and two charts, blood flow index (BFI) and blood volume index (BVI). Each has its own scale, and they share the time axis, phase bands, and a synced crosshair. An optional camera-spread band shows the middle 50% of cameras.
- **Present**: for the demo screen. Controls are hidden. The phase becomes a breathing circle that rises and falls gently at baseline, holds full during the breath hold, and moves faster during recovery, ringed by the timed-phase countdown. Heart rate, contact quality and stress sit beside it.

The look is a light, clinical base: flat surfaces, hairline borders, mono numerals. Dark tokens remain in `styles.css` but are off (`data-theme="light"` on `<html>`).

From any working directory: `.venv/bin/python serve.py --dev-feed`.

## Lanes

| Lane | Paths | Role |
| :- | :- | :- |
| Dashboard, session/phase logger | `dashboard/`, `session/` | Live UI, hub, phase timer, LSL phase markers |
| Lane 1 Open-Motion | `ingest/omotion_source.py`, `features/cq_score.py`, `features/pulse_hr.py`, `replay_csv.py` | CSV replay, side averages, contact quality, optical heart rate |
| Lane 2 Mentalab ECG | `ingest/mentalab_source.py`, `features/ecg_hrv.py`, `features/hr_compare.py`, `replay_mentalab.py` | CSV replay, ECG heart rate, RMSSD, SDNN, optical cross-check |
| Lane 4 protocol and alert math | `features/stress_index.py`, `features/track3_classifier.py`, `protocol/breathhold.md` | CQ-gated stress index, recovery time constant, breath-hold protocol |

Producers talk to the dashboard only through [dashboard/SCHEMA.md](dashboard/SCHEMA.md). Offline replay CSVs are a separate contract, below. They are not the WebSocket frames.

## Status

| Milestone | State |
| :- | :- |
| 1. Server, hub, ingest and browser sockets, live BFI charts from replay | Done |
| 2. Session/phase logger: session bar, phase buttons and timer, `events.csv`, chart shading, LSL markers | Done |
| 3. Contact quality, dual heart rate, stress and alert panels | CQ, dual heart rate, and the CQ-gated stress index exist as features. Dashboard panels for them are still planned |

## Versions

Python 3.12, pins in `pyproject.toml`, locked in `uv.lock`. Dashboard: fastapi 0.143.0, uvicorn 0.54.0, websockets 17.2, pylsl 1.18.5 (bundles liblsl 1.18). Replay: numpy, pandas, scipy, neurokit2. Dev: pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1, ruff 0.17.0. Vendored in `dashboard/static/vendor/`: uPlot 1.6.32 (MIT), Geist and Geist Mono variable fonts 5.3.0 from Fontsource (OFL-1.1). Chart and status colors come from the dataviz reference palette. The left/right pair passes its palette validator in light and dark.

The Mentalab device path runs in its own environment (`explorepy==4.5.1`, `explorepy push2lsl`) because explorepy hard-pins old numpy, scipy, and pylsl. CSV replay does not import explorepy.

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

`features/pulse_hr.py` detrends BFI and reports the strongest frequency between 0.7 and 3.0 Hz (42 to 180 bpm).

- One rate for the whole clip. Beat-to-beat intervals and HRV are Lane 2.
- Lane 2 can compare this number with the ECG rate. That comparison is a research cross-check.
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

## Lane 2 Mentalab ECG

Primary input is an explorepy ExG export, `{name}_ExG.csv`. `record_data(..., file_type="csv")` writes a header row `TimeStamp,ch1,ch2,...` and no units row. `TimeStamp` is seconds. Channel values are microvolts. The sampling rate is not in the file (Explore devices are 250, 500, or 1000 Hz); replay takes the median step from `TimeStamp`. A renamed file with `timestamp_s` and `ecg_uv` is accepted too. Pass `--channel ch2` to pick a lead other than the lowest `chN`. Orientation files (`*_ORN.csv`) are a different export and are rejected.

```bash
python stress-alert/replay_mentalab.py \
  --csv stress-alert/data/synthetic_ecg.csv \
  --out stress-alert/data/ecg_trace.csv \
  --optical-hr 72
```

`synthetic_ecg.csv` is 5000 samples at 250 Hz with a 72 bpm ECG. The command prints duration, sample rate, mean heart rate near 72, mean NN, SDNN, and RMSSD. `--optical-hr` is the Lane 1 `optical_hr_bpm` figure. The CLI prints the absolute difference and that difference as a percent of the ECG rate.

`ecg_trace.csv` (one row per sample):

| Column | Meaning |
| :- | :- |
| `timestamp_s` | `TimeStamp` from the Explore file, in seconds. The synthetic file starts at 0. A device file keeps the device clock |
| `ecg_uv` | The chosen lead, microvolts |
| `hr_bpm` | NeuroKit2 `ECG_Rate`, interpolated between R peaks. Blank where the rate is missing |

`ecg_trace_metrics.csv` (one row for the clip; written next to `--out` unless `--metrics` is set):

| Column | Meaning |
| :- | :- |
| `duration_s`, `sample_rate_hz`, `channel` | Clip length, median rate, lead name |
| `hr_bpm_mean` | 60000 / mean RR (`HRV_MeanNN`) |
| `hrv_mean_nn_ms`, `hrv_sdnn_ms`, `hrv_rmssd_ms` | Mean RR, SDNN, and RMSSD in milliseconds |
| `n_peaks` | R peaks NeuroKit2 kept |

On the live socket, send `{"type": "hr", "t": <pylsl.local_clock()>, "source": "ecg", "bpm": <hr_bpm_mean>}` as specified in SCHEMA.md. Do not send the Explore `TimeStamp` as `t` until it has been mapped onto `pylsl.local_clock()`. `features/hr_compare.py` compares per-sample rates on shared windows only when both traces already share a clock.

Clips shorter than 8 seconds are rejected. SDANN and the frequency-domain HRV set are left out: they need minutes of data.

Live Explore recording, only with a paired device, and in the explorepy environment rather than this one:

```python
from ingest.mentalab_source import start_live_ecg

explore = start_live_ecg(
    device_name="Explore_XXXX",
    file_name="breathhold",
    duration_sec=60,
    allow_live=True,
)
```

`allow_live=False` raises. Without `explorepy` installed, the live call raises `ImportError` and says CSV replay does not need it. `record_data` writes `breathhold_ExG.csv`. Replay that file with the CLI above. Upstream connect and record examples: https://github.com/Mentalab-hub/explorepy/blob/master/docs/usage.rst

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

Lane 1, Lane 2, Lane 4, and the dashboard tests, from the repo root, using the project environment (`uv sync` installs pytest, which the dashboard tests import):

```bash
stress-alert/.venv/bin/python -m unittest discover -s stress-alert/tests -t stress-alert
```

Dashboard, from `stress-alert/`:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Data

`data/sample_scan.csv` is copied from Openwater's [openmotion-bloodflow-app](https://github.com/OpenwaterHealth/openmotion-bloodflow-app) (`resources/sample_scan.csv` at 0be3e90, Apache-2.0): 30 s, 16 cameras, 40 Hz, corrected BFI/BVI. `synthetic_scan.csv` and `synthetic_ecg.csv` are the 72 bpm offline fixtures. Recordings of team members go in `sessions/`, which is gitignored. See `data/README.md`.
