# stress-alert, Lane 1 (Open-Motion)

Offline ingest for the hackathon stress-alert demo. Lane 1 reads a corrected Open-Motion scan CSV, writes left and right BFI/BVI plus a 0 to 1 contact-quality score, and estimates an optical heart rate from BFI.

For research. These numbers are not a diagnosis, a screening result, or a treatment signal.

Organizers told the team that human recordings are allowed for this project. Keep claims research-only anyway. Do not change safety-critical optical output, and do not enable the laser from this package. Station scans belong on the Windows host, using the SDK examples below.

Mentalab, the Streamlit or FastAPI dashboard, and `stress_index` are other lanes. `protocol/`, `sync/`, and `dashboard/` are placeholders only.

## Setup

Python 3.12, from the repo root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r stress-alert/requirements.txt
```

`numpy`, `pandas`, and `scipy` are the replay stack. `openmotion-sdk` and `pylsl` stay optional: the first is the live station path, the second is the sync lane. Neither is imported by CSV replay.

```bash
pip install openmotion-sdk   # station host only
```

Import Lane 1 without installing the package:

```bash
export PYTHONPATH=stress-alert
python -c "from ingest.omotion_source import replay_scan; print(replay_scan)"
```

## CSV replay

A tiny synthetic scan is already in the repo (640 frames at 40 Hz, a 72 bpm pulse on BFI, camera r8 marked `nan_filled`):

```bash
python stress-alert/replay_csv.py \
  --csv stress-alert/data/synthetic_scan.csv \
  --out stress-alert/data/side_averages.csv
```

The command prints frame count, duration, sample rate, mean `bfi_l`, `bfi_r`, `bvi_l`, `bvi_r`, mean CQ, how many frames tripped bad coupling, and `optical_hr_bpm`. On the synthetic file the heart-rate line should land near 72.

`--window-s 1` writes a 1 second trailing mean of the side averages. Heart rate still uses the per-frame trace, because smoothing the pulse makes the peak worse. The default window is 0: one output row per input frame.

Drop a real corrected scan at `stress-alert/data/sample_scan.csv` and pass that path instead. Column layout matches `openmotion-bloodflow-app/resources/sample_scan.csv`: `frame_id`, `timestamp_s`, `bfi_l1`..`bfi_l8`, `bfi_r1`..`bfi_r8`, and the same 16 columns for `bvi`, `mean`, `contrast`, `temp`, and `quality`. See `data/README.md`.

## What other lanes should read

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
| `ingest/omotion_source.py` | CSV replay, side averages, output CSV, gated live scan |
| `features/cq_score.py` | Per-camera quality or contact-quality to one 0 to 1 score and `bad_coupling` |
| `features/pulse_hr.py` | Dominant-frequency optical heart rate from BFI |
| `replay_csv.py` | Demo CLI |

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
