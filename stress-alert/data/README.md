`sample_scan.csv` is a real Openwater corrected scan, not synthetic, and it's what the dashboard `--replay` streams by default. It is copied from `openmotion-bloodflow-app/resources/sample_scan.csv` (0be3e90, Apache-2.0): `frame_id`, `timestamp_s`, `bfi_l1`..`bfi_l8`, `bfi_r1`..`bfi_r8`, and the same pattern for `bvi`, `mean`, `contrast`, `temp`, and `quality`.

No synthetic data ships here (removed on 2026-10-24). To replay a team recording, pass its corrected CSV: `uv run python -m dashboard --replay path/to/scan.csv`.

`side_averages.csv` is Lane 1 replay output. Do not commit it.

Recordings of team members go in `sessions/`, which is gitignored.
