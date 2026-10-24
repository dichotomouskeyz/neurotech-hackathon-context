# stress-alert

Offline ingest for the hackathon stress-alert demo.

- Lane 1 reads a corrected Open-Motion scan CSV, writes left and right BFI/BVI plus a 0 to 1 contact-quality score, and estimates an optical heart rate from BFI.
- Lane 2 reads a Mentalab Explore ECG CSV, writes a trace the dashboard can plot beside those side averages, and estimates heart rate plus RMSSD and SDNN with NeuroKit2. That ECG rate is the research cross-check for the optical rate, and the recovery feature after the breath-hold task.

For research. These numbers are not a diagnosis, a screening result, or a treatment signal.

Organizers told the team that human recordings are allowed for this project. Keep claims research-only anyway. Do not change safety-critical optical output, and do not enable the laser from this package. Station scans belong on the Windows host, using the SDK examples below.

The Streamlit or FastAPI dashboard and `stress_index` are other lanes. `protocol/`, `sync/`, and `dashboard/` stay placeholders.

## Setup

Python 3.12, from the repo root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r stress-alert/requirements.txt
```

`numpy`, `pandas`, `scipy`, and `neurokit2` are the replay stack. Lane 1 does not import NeuroKit2. Lane 2 does. `openmotion-sdk`, `explorepy`, and `pylsl` stay optional: station Open-Motion, live Mentalab, and the sync lane. CSV replay does not import them.

```bash
pip install openmotion-sdk   # Open-Motion station host only
pip install explorepy         # paired Explore device only
```

Import either lane without installing the package:

```bash
export PYTHONPATH=stress-alert
python -c "from ingest.omotion_source import replay_scan; print(replay_scan)"
python -c "from ingest.mentalab_source import read_ecg_csv; print(read_ecg_csv)"
```

## Lane 1 CSV replay

A tiny synthetic scan is already in the repo (640 frames at 40 Hz, a 72 bpm pulse on BFI, camera r8 marked `nan_filled`):

```bash
python stress-alert/replay_csv.py \
  --csv stress-alert/data/synthetic_scan.csv \
  --out stress-alert/data/side_averages.csv
```

The command prints frame count, duration, sample rate, mean `bfi_l`, `bfi_r`, `bvi_l`, `bvi_r`, mean CQ, how many frames tripped bad coupling, and `optical_hr_bpm`. On the synthetic file the heart-rate line should land near 72.

`--window-s 1` writes a 1 second trailing mean of the side averages. Heart rate still uses the per-frame trace, because smoothing the pulse makes the peak worse. The default window is 0: one output row per input frame.

Drop a real corrected scan at `stress-alert/data/sample_scan.csv` and pass that path instead. Column layout matches `openmotion-bloodflow-app/resources/sample_scan.csv`: `frame_id`, `timestamp_s`, `bfi_l1`..`bfi_l8`, `bfi_r1`..`bfi_r8`, and the same 16 columns for `bvi`, `mean`, `contrast`, `temp`, and `quality`. See `data/README.md`.

## Lane 2 Mentalab ECG

Primary input is an explorepy ExG export, `{name}_ExG.csv`. `record_data(..., file_type="csv")` writes a header row `TimeStamp,ch1,ch2,...` and no units row. `TimeStamp` is seconds. Channel values are microvolts. The sampling rate is not in the file (Explore devices are 250, 500, or 1000 Hz); replay takes the median step from `TimeStamp`. A renamed file with `timestamp_s` and `ecg_uv` is accepted too. Pass `--channel ch2` to pick a lead other than the lowest `chN`. Orientation files (`*_ORN.csv`) are a different export and are rejected.

A synthetic Explore-shaped file is already in the repo (5000 samples, 250 Hz, a 72 bpm ECG):

```bash
python stress-alert/replay_mentalab.py \
  --csv stress-alert/data/synthetic_ecg.csv \
  --out stress-alert/data/ecg_trace.csv \
  --optical-hr 72
```

The command prints duration, sample rate, mean heart rate, mean NN, SDNN, RMSSD, and peak count. On the synthetic file the heart-rate line should land near 72. `--optical-hr` is the Lane 1 `optical_hr_bpm` figure. The CLI prints the absolute difference and that difference as a percent of the ECG rate. That is a demo cross-check, not a clinical comparison.

Drop a recorded `*_ExG.csv` under `stress-alert/data/` and pass that path instead. See `data/README.md`.

### What the dashboard should read

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

Plot `ecg_trace.csv` against time beside Lane 1 `side_averages.csv`. The two `timestamp_s` columns are separate clocks until the sync lane aligns them. Use `hr_bpm_mean` against Lane 1 `optical_hr_bpm` for the pitch cross-check. `features/hr_compare.py` also compares per-sample rates on shared windows when both traces already share a clock.

Clips shorter than 8 seconds are rejected. SDANN and the frequency-domain HRV set are left out on purpose: they need minutes of data.

Live Explore recording, only with a paired device:

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

## Lane 1 output

`side_averages.csv`:

| Column | Meaning |
| :- | :- |
| `timestamp_s` | Frame time from the scan CSV, seconds |
| `bfi_l`, `bfi_r` | Mean of finite cameras on that side. Blank cells were `NaN` and were skipped, not zeroed |
| `bvi_l`, `bvi_r` | Same for blood volume index |
| `cq` | Mean per-camera quality, 0 to 1. Blank when the scan has no `quality_*` columns |

`bad_coupling` is not a column. It is true when `cq` is strictly below 0.5, and the CLI counts those frames. Treat that as "do not trust pulse features on this window."

A later SDK build dropped `quality_*` from the corrected CSV and left quality on the scan database. Replay still runs. `cq` is blank in that case. Contact-quality checks from the station are a separate input to `features/cq_score.py` (`passed`, or `light_avg_dn` and `dark_max_dn`).

## Modules

| Path | Role |
| :- | :- |
| `ingest/omotion_source.py` | Lane 1 CSV replay, side averages, output CSV, gated live scan |
| `features/cq_score.py` | Per-camera quality or contact-quality to one 0 to 1 score and `bad_coupling` |
| `features/pulse_hr.py` | Dominant-frequency optical heart rate from BFI |
| `replay_csv.py` | Lane 1 demo CLI |
| `ingest/mentalab_source.py` | Lane 2 Explore CSV replay, trace and metrics CSV, gated live record |
| `features/ecg_hrv.py` | NeuroKit2 heart rate, SDNN, and RMSSD |
| `features/hr_compare.py` | Optical versus ECG rate, clip-level or on shared windows |
| `replay_mentalab.py` | Lane 2 demo CLI |

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

## Optical heart rate

`features/pulse_hr.py` detrends BFI and reports the strongest frequency between 0.7 and 3.0 Hz (42 to 180 bpm).

- One rate for the whole clip. Beat-to-beat intervals and HRV need a different estimator.
- The figure has not been checked against ECG.
- Clips shorter than about 8 seconds return no rate.
- Motion and bad coupling can invent a peak. Gate on CQ first.
- Respiration sits near 0.2 Hz and falls outside the search band. A strong oscillation inside the band is reported, cardiac or otherwise.
- `hr_confidence` near 1 is a sharp peak. Near 0.5 the band is flat and no rate is printed.

## Tests

```bash
python -m unittest discover -s stress-alert/tests -t stress-alert
```
