`sample_scan.csv` is the Openwater corrected scan the dashboard `--dev-feed` replays. It is copied from `openmotion-bloodflow-app/resources/sample_scan.csv` (0be3e90): `frame_id`, `timestamp_s`, `bfi_l1`..`bfi_l8`, `bfi_r1`..`bfi_r8`, and the same pattern for `bvi`, `mean`, `contrast`, `temp`, and `quality`.

`synthetic_scan.csv` is a small Lane 1 stand-in: 640 frames at 40 Hz, a 72 bpm pulse on BFI, camera r8 marked `nan_filled`. Regenerate it with `python stress-alert/data/make_synthetic_scan.py`.

`side_averages.csv` is Lane 1 replay output. Do not commit it.

Lane 2 reads an explorepy `*_ExG.csv` (`TimeStamp`, `ch1`... in microvolts). `synthetic_ecg.csv` is a committed stand-in: 5000 samples at 250 Hz, a 72 bpm ECG on `ch1`. Regenerate it with `python stress-alert/data/make_synthetic_ecg.py` (needs neurokit2). `ecg_trace.csv` and `ecg_trace_metrics.csv` are replay output. Do not commit them.

Recordings of team members go in `sessions/`, which is gitignored.
