<!--
Source: https://docs.google.com/document/d/1EZLYCaoG85xlRGpJDvhnk7DNJXzRvOD0-C6tjOzwKH4/edit
Title: Openwater Tracks
Captured: 2026-10-24 via Google Drive connector, verbatim text export.
-->

# 5. Challenge Tracks

Openwater is sponsoring challenge tracks rather than fixed project assignments. Each track names a problem space worth exploring, explains why it matters, and offers optional seed ideas. Teams pick one track or propose their own under the Wildcard track, and are free to take a seed idea, remix several, or invent something new. The goal is a creative, working demonstration by Sunday afternoon, not the completion of a pre-written spec. The tracks are suggestions to inspire teams; they do not need to be followed strictly.

> **Data and scope for all tracks.** Every track can be completed with provided datasets, open-source repositories, simulation, and software. Physical devices are shared stations available in scheduled slots. **No track involves placing a device on a person or collecting human data.** Outputs are research engineering demonstrations, not diagnostic, screening, or clinical-decision tools.

| Track | Platform | Example directions | Typical skills |
| :-: | :-: | :-: | :-: |
| 1 · Signal & Physiology | Open-Motion | Pulse and heart rate, respiration, HRV, artifact rejection, left-right asymmetry | DSP, Python |
| 2 · Real-Time Viz & Interface | Open-Motion | Dashboards, laterality views, annotation, replay | UI/UX, visualization |
| 3 · ML & Brain-State | Open-Motion | Cognitive-load or task classification on provided data, leakage-free evaluation | ML, statistics |
| 4 · Developer Tools & SDK | Both | Logging, LSL or REST or CLI integrations, exports, tests, docs | Software engineering |
| 5 · Acoustic Simulation & Planning | Open-LIFU | Beam steering and pressure-field simulation, target workflows, SlicerOpenLIFU UX | Acoustics, numerical methods, Qt |
| 6 · Imaging & Registration | Open-LIFU | MRI tissue segmentation, landmark detection, surface-registration error metrics | Medical imaging, 3D geometry, ML |
| 7 · Hardware & Wearables | Both | Headset fit and coupling, fixtures, firmware or FPGA study on the bench | ME, EE, firmware |
| 8 · Wildcard | Any | Anything creative that fits none of the above | Any |

## 5.1 Track 1: Signal & Physiology (Open-Motion)

Making sense of blood flow. Every downstream application stands on clean physiology extraction from the BFI and BVI streams.

- **Seed ideas:** pulse and heart-rate extraction from BFI; respiration estimation and HRV; motion-artifact rejection with a continuous 0 to 1 signal-quality index; blood-flow laterality and inter-hemispheric asymmetry.
- **A strong entry:** a robust, documented signal pipeline with an honest evaluation and a clear analysis of when and why it fails.
- **Data:** provided pre-recorded and synthetic P-SCOS, BFI, and BVI datasets.

## 5.2 Track 2: Real-Time Visualization & Interface (Open-Motion)

Make the signal legible. A hemodynamic stream only creates value if a person can read it at a glance.

- **Seed ideas:** low-latency multi-channel dashboards for BFI and BVI; laterality views with configurable asymmetry display; event annotation, session export, and replay; a "replay from CSV" teaching mode.
- **A strong entry:** a responsive interface someone would want to use, with a clear UX and performance rationale.
- **Data:** provided datasets and replayed logs; live stream from the shared station when available.

## 5.3 Track 3: ML & Brain-State Classification (Open-Motion)

Infer states from hemodynamics. Rigorous evaluation matters more here than a headline accuracy number.

- **Seed ideas:** cognitive-load or attention detection; event or task classification from hemodynamic patterns; exploratory modeling of brain-state dynamics, with candid caveats about single-modality inference.
- **A strong entry:** leakage-free, subject-wise evaluation with ROC and confusion analysis, a baseline comparison, and a grounded interpretation of what the model learned. A well-run null result is a good result.
- **Data:** provided or synthetic datasets only. No new human data is collected at this event, and no diagnostic or screening claims should be made.

## 5.4 Track 4: Developer Tools, SDK & Integrations (Both)

Make the platform easier to build on. Tooling built this weekend can help every future developer on either platform.

- **Seed ideas:** openmotion-sdk data logging with session metadata; Lab Streaming Layer, REST, or CLI integrations; standardized exports; a replay server; unit tests, CI workflows, and improved documentation; helper tooling around openlifu-python or the openlifu-sdk.
- **A strong entry:** an upstream-able pull request with tests and docs.
- **Data:** provided datasets, replayed logs, and sample databases.

## 5.5 Track 5: Acoustic Simulation & Planning (Open-LIFU)

Show where the energy goes before anything is switched on. Simulation and planning tools help researchers understand where a configuration is expected to concentrate acoustic pressure.

- **Seed ideas:** reproducible simulation workflow from transducer configuration and target to pressure field and focal metrics; comparison of candidate steering configurations; a bounded UX improvement to SlicerOpenLIFU or the desktop application.
- **Tank tie-in:** compare a simulated focal path against the live raster on the demo tank, or submit a scan pattern for Openwater staff to run during a scheduled slot (§4.3).
- **A strong entry:** a workflow that moves from defined inputs to quantitative focal outputs with no hidden manual steps.
- **Data:** openlifu-sample-database and simulation examples. Planning software is not used to direct sonication of any person.

## 5.6 Track 6: Imaging & Registration (Open-LIFU)

Anatomy in, coordinates out. Localization and registration quality set the ceiling for any planning workflow.

- **Seed ideas:** MRI tissue segmentation into brain, bone, scalp, air, and CSF; automatic landmark detection (nose tip, left and right tragus) on MRI-derived surfaces or photogrammetry meshes; surface-registration error metrics and heatmaps.
- **A strong entry:** reproducible pipeline with real quantitative error (Dice, millimeters) rather than only attractive images.
- **Data:** de-identified sample imaging and photogrammetry data supplied by Openwater, used only under the event data-handling rules.

## 5.7 Track 7: Hardware & Wearables (Both)

The physical device. Signal quality begins at the sensor, and software begins at the firmware.

- **Seed ideas:** Open-Motion headset fit, sensor coupling, and mounting concepts validated on phantoms or benchtop fixtures; firmware or FPGA study using the open repositories; mechanical or enclosure improvements from the open CAD; electrical design review.
- **A strong entry:** a bench-validated improvement with clear before-and-after evidence and documented trade-offs.
- **Data:** open hardware files, phantoms and fixtures, and the shared stations. No modification of safety-critical optical or acoustic output.

## 5.8 Track 8: Wildcard / Open Innovation

The best hackathon ideas often do not fit the categories. Teaching tools, data-art, accessibility-focused uses, and cross-instrument mashups are welcome, provided they are achievable in a weekend, buildable with the provided resources, and consistent with the development-only scope. Openwater mentors will help teams right-size an idea at kickoff.
