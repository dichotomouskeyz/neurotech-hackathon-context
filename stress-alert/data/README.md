Drop a corrected Open-Motion scan here as `sample_scan.csv`.

The public example is `openmotion-bloodflow-app/resources/sample_scan.csv`: `frame_id`, `timestamp_s`, `bfi_l1`..`bfi_l8`, `bfi_r1`..`bfi_r8`, and the same pattern for `bvi`, `mean`, `contrast`, `temp`, and `quality`.

`synthetic_scan.csv` is a committed stand-in so replay works with no station file. It is 640 frames at 40 Hz with a 72 bpm pulse on BFI. Camera r8 is blank and marked `nan_filled`. Regenerate it with `python stress-alert/data/make_synthetic_scan.py`.

`side_averages.csv` is replay output. Do not commit it.
