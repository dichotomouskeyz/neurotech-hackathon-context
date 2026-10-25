# Open-Motion

Working reference for the team's platform choice. Sources: Openwater docs (`openwater-docs` @ ebb3db0, 2026-10-24), `openmotion-sdk` @ 58dbbe2, `openmotion-bloodflow-app` @ 0be3e90.

## Access at this event

The team has the Open-Motion station for the whole weekend (per Jahlon, 2026-10-24). This differs from the SOW, which plans 20 to 30 minute sign-up slots.

Self-testing: per Jahlon (2026-10-24), Openwater approved team members wearing Open-Motion for self-tests. That overrides the SOW §6 line "not applied to any person, including self-testing by team members or mentors" for this team. The `stress-alert` breath-hold protocol depends on it. Recordings stay out of git.

Rules that still apply:

- Do not open the console. It contains a Class 3 laser source and high voltage. No changes to safety-critical optical output.
- No diagnostic, screening, or clinical claims.

The app is the repository root. See [README.md](../../README.md).

## What it measures

Pulsed speckle contrast optical spectroscopy (P-SCOS). A 795 nm pulsed laser lights tissue through a diffuser. Moving red blood cells blur the speckle pattern, so lower speckle contrast means more flow.

- **BFI** (blood flow index): from speckle contrast K = σ/μ.
- **BVI** (blood volume index): from mean intensity. More blood absorbs more light.
- 40 Hz, depth up to about 3.5 cm, left and right hemodynamic traces.

Calibration is an affine map per camera (`omotion/pipeline/stages/bfi_bvi.py`):

```
bfi = (1 - (K - c_min) / (c_max - c_min)) * 10
bvi = (1 - (m - i_min) / (i_max - i_min)) * 10
```

`c_min, c_max, i_min, i_max` are (2, 8) arrays loaded from console EEPROM or computed by `CalibrationWorkflow`. Both indices are relative, roughly 0 to 10, not absolute physiological units.

## Hardware

| Part | Key facts |
| :- | :- |
| Console | USB-C to the host (Openwater cable 100-00049 only), SMA trigger in, SMA sync out, left and right electrical and optical ports |
| Sensor modules | Two (left, right). 8 OX02C1B CMOS cameras each, 1920 x 1280, 40 Hz, 2 m cable |
| Laser | Class 1 at the output, 795 nm, 250 to 1000 µs pulses, 40 Hz, 12 mW average |
| Host | Windows laptop supplied by Openwater. SDK supports Windows 11 today; macOS and Linux are roadmap |

Camera layout per module (software channel = camera number minus 1):

```
Cam 1 | Cam 8    top
Cam 2 | Cam 7
Cam 3 | Cam 6
Cam 4 | Cam 5    bottom
```

Per-camera analog gain by channel is `[16, 4, 2, 1, 1, 2, 4, 16]`, so the outer cameras run at higher gain. Named groups: outer (1, 4, 5, 8), inner (2, 3, 6, 7), top pair, bottom pair.

The SMA trigger and sync ports are the hook for synchronizing with external devices, such as stimulus presentation or another instrument.

## Data path

```
Camera FPGA (Verilog)      2 MP frame -> 1024-bin histogram, 40 fps
  -> Aggregator MCU (STM32) 8 cameras over SPI, out over USB HS
  -> Console MCU (STM32)    sync pulses, laser timing, safety interlocks
  -> Host SDK (Python)      histograms -> BFI/BVI, CSV or SQLite
  -> Bloodflow app (PyQt6)  live plots, history, replay
```

Images never leave the camera. The host only sees histograms, which is enough for mean and variance and therefore speckle contrast.

SDK pipeline stages (`omotion/pipeline/`, docs/SciencePipeline.md): frame classification (drops 9 warmup frames, schedules a dark frame every 600 frames, or 15 s), timestamp repair, noise floor, moments, pedestal subtraction, dark correction, shot-noise correction, BFI/BVI, side average. Stages are pure transforms. Output goes to sinks on named channels (`raw`, `live`, `live_side`, `final`, `diagnostics`). A new consumer is a class with a `channels` set and a `consume(channel, payload)` method, with no pipeline changes. That is the cleanest extension point for an LSL bridge, a WebSocket stream, or a custom live view.

## SDK entry point

```python
from omotion import MotionInterface
from omotion.ScanWorkflow import ScanRequest

iface = MotionInterface(data_dir="C:/scans", operator_id="team")
iface.start(wait=True, wait_timeout=3.0)
iface.start_scan(ScanRequest(subject_id="phantom-01", duration_sec=60,
                             left_camera_mask=0xFF, right_camera_mask=0xFF))
iface.scan_workflow.await_complete()
iface.stop()
```

With no database configured, each scan writes a corrected CSV under `data_dir`. `scripts/visualize_scan.py` turns a scan CSV into an interactive HTML plot. `scripts/sdk_examples.py` covers connect, configure, contact quality, scan, and read-scan.

## Data formats

**Corrected per-camera CSV** (e.g. `openmotion-bloodflow-app/resources/sample_scan.csv`): `frame_id`, `timestamp_s`, then for each of `bfi`, `bvi`, `mean`, `contrast`, `quality`, `temp` one column per side and camera (`bfi_l1` to `bfi_l8`, `bfi_r1` to `bfi_r8`). 98 columns.

**Raw histogram CSV** (CsvSink, replayable through `CsvReplaySource`): `cam_id, frame_id, timestamp_s, type, 0..1023, temperature, sum, tcm, tcl, pdc`. One file per side.

**SQLite scan DB** when `scan_db_path` is set (docs/ScanDatabase.md).

## Checked on Jahlon's Mac (2026-10-24)

- `openmotion-sdk` installs and imports under Python 3.12 (version 1.14.0.post1.dev2). PyQt6 is optional; the SDK falls back to shim signals.
- `MotionInterface(demo_mode=True)` connects nothing, and `start_scan` runs over an empty source. It wrote only a telemetry CSV, no BFI/BVI frames. The README's claim that demo mode generates synthetic data did not hold in this test.
- `sample_scan.csv` is 30 s (1201 rows at 40 Hz, 16 cameras). BFI median 2.19 (range -0.39 to 6.20), BVI median 6.25, contrast median 0.30, every quality value `ok`. It works for building and testing off the station.
- libusb is not installed on the Mac (`brew install libusb` if ever needed). Live hardware runs on the Windows host anyway.

## Track fit

| Track | Open-Motion angle |
| :- | :- |
| 1 Signal | Pulse, respiration, HRV, signal-quality index from BFI on provided data |
| 2 Viz | Live dashboard as a pipeline sink, laterality view, replay-from-CSV teaching mode |
| 3 ML | Cognitive load or task classification on provided data with subject-wise evaluation. Closest fit to the event prompt |
| 4 Dev tools | LSL or WebSocket sink, CLI, standardized export, tests. Upstream PR scores on the rubric |
| 7 Hardware | Phantom and fixture work on coupling and fit, using the station all weekend |

Weekend-long station access favors projects that use live phantom data, such as a validated signal-quality index, coupling and fixture studies, or a real-time sink tested against the device.

## Judging (SOW Annex B, draft weights)

Innovation 25%, technical merit 25%, execution and demo 25%, open-source contribution 15%, impact 10%. Judges include Dan Blizinski and an Openwater engineer. Demos run Sunday 3:00 to 5:00 pm.
