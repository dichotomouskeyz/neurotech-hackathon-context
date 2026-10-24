# Challenge tracks

Condensed from the Openwater tracks document. Full wording is in `sources/openwater-tracks.md`.

Open-Motion streams: **BFI** (blood flow index) and **BVI** (blood volume index), derived from **P-SCOS** optical measurements. Open-LIFU is low-intensity focused ultrasound.

| # | Track | Platform | Skills |
| :- | :- | :- | :- |
| 1 | Signal & Physiology | Open-Motion | DSP, Python |
| 2 | Real-Time Viz & Interface | Open-Motion | UI/UX, visualization |
| 3 | ML & Brain-State | Open-Motion | ML, statistics |
| 4 | Developer Tools & SDK | Both | Software engineering |
| 5 | Acoustic Simulation & Planning | Open-LIFU | Acoustics, numerical methods, Qt |
| 6 | Imaging & Registration | Open-LIFU | Medical imaging, 3D geometry, ML |
| 7 | Hardware & Wearables | Both | ME, EE, firmware |
| 8 | Wildcard | Any | Any |

Raymond's planning doc has an older seven-row table that omits Track 4. The Openwater doc has all eight.

## 1. Signal & Physiology

- **Ideas:** pulse and heart rate from BFI; respiration and HRV; motion-artifact rejection with a continuous 0 to 1 signal-quality index; inter-hemispheric blood-flow asymmetry.
- **Strong entry:** documented pipeline, honest evaluation, clear analysis of when and why it fails.
- **Data:** pre-recorded and synthetic P-SCOS, BFI, BVI.

## 2. Real-Time Visualization & Interface

- **Ideas:** low-latency multi-channel BFI/BVI dashboards; configurable laterality views; annotation, export, replay; a replay-from-CSV teaching mode.
- **Strong entry:** a responsive interface with a clear UX and performance rationale.
- **Data:** provided datasets and replayed logs; live station stream when available.

## 3. ML & Brain-State Classification

- **Ideas:** cognitive load or attention detection; task classification from hemodynamics; brain-state dynamics with caveats about single-modality inference.
- **Strong entry:** leakage-free subject-wise evaluation, ROC and confusion analysis, baseline comparison, grounded interpretation. A well-run null result counts.
- **Data:** provided or synthetic only. No diagnostic or screening claims.

## 4. Developer Tools, SDK & Integrations

- **Ideas:** openmotion-sdk logging with session metadata; LSL, REST, or CLI integrations; standardized exports; replay server; tests, CI, docs; tooling around openlifu-python or openlifu-sdk.
- **Strong entry:** an upstream-able pull request with tests and docs.
- **Data:** provided datasets, replayed logs, sample databases.

## 5. Acoustic Simulation & Planning

- **Ideas:** reproducible workflow from transducer configuration and target to pressure field and focal metrics; comparing steering configurations; a bounded UX improvement to SlicerOpenLIFU or the desktop app.
- **Tank tie-in:** compare a simulated focal path against the live raster on the demo tank, or submit a scan pattern for Openwater staff to run in a scheduled slot.
- **Strong entry:** defined inputs to quantitative focal outputs with no hidden manual steps.
- **Data:** openlifu-sample-database and simulation examples.

## 6. Imaging & Registration

- **Ideas:** MRI segmentation into brain, bone, scalp, air, CSF; landmark detection (nose tip, left and right tragus) on MRI surfaces or photogrammetry meshes; surface-registration error metrics and heatmaps.
- **Strong entry:** reproducible pipeline with quantitative error (Dice, millimeters).
- **Data:** de-identified imaging and photogrammetry from Openwater, under event data-handling rules.

## 7. Hardware & Wearables

- **Ideas:** Open-Motion headset fit, sensor coupling, mounting on phantoms or bench fixtures; firmware or FPGA study; enclosure improvements from open CAD; electrical design review.
- **Strong entry:** bench-validated improvement with before-and-after evidence and documented trade-offs.
- **Data:** open hardware files, phantoms, fixtures, shared stations. No changes to safety-critical optical or acoustic output.

## 8. Wildcard

Teaching tools, data art, accessibility uses, and cross-instrument mashups are welcome if achievable in a weekend, buildable with provided resources, and within the development-only scope. Openwater mentors help right-size ideas at kickoff.
