# Dashboard message contract

Producers (ingest, features, the phase logger) send JSON to the dashboard over a WebSocket. The dashboard validates every frame and rebroadcasts valid ones to browsers. The source of truth is `dashboard/schema.py`. This file is the readable copy.

## Connecting

```
ws://<dashboard-host>:8765/ws/ingest?source=<your-name>
```

- `source` names your producer (for example `omotion`, `features`). The dashboard shows a status chip for it, green while connected.
- Send one frame or a list of frames per message. At 40 Hz, batch about 4 frames per message.
- Invalid frames are dropped. The dashboard replies on the same socket with `{"type": "error", "errors": ["frame 1: hr.bpm: ..."]}`. Valid frames in the same message still go through.
- Python client: `websockets.asyncio.client.connect`. See `dashboard/dev_feed.py` for a working producer.

## Time

`t` is seconds on **LSL `pylsl.local_clock()`** of the machine running the dashboard. `GET /api/clock` returns the current value.

- A producer on the same machine calls `pylsl.local_clock()`.
- A producer reading from an LSL inlet uses the sample timestamp plus `inlet.time_correction()`.
- Do not send `time.monotonic()` or wall-clock time. On macOS, `local_clock()` and `time.monotonic()` differ by millions of seconds, and frames on the wrong clock land off the chart.

## Frames

| type | fields | notes |
| :- | :- | :- |
| `bfi`, `bvi` | `t`, `left[8]`, `right[8]` | one value per camera, `null` for a disabled camera |
| `hr` | `t`, `source` (`optical`), `bpm` | 0 < bpm < 300. Optical heart rate from the BFI pulse, side panel only. It does not set the stress label. ECG was dropped on 2026-10-24 and `ecg` is rejected |
| `cq` | `t`, `left`, `right` | contact quality, 0 to 1, or `null` when that side has no contact measurement. A missing side is `null`, not 1. The live device fills this from per-camera light and dark DN on the Open-Motion `live` batch (the same thresholds as `features/cq_score.py`), not from the pipeline timestamp-quality flag (`ok` means the timestamp was unchanged and is not contact) |
| `stress` | `t`, `index`, `recovery_score` (optional), `alert` (bool), `reason`, `tau_s` (optional), `alert_at` (optional), `channels` (optional), `gate` (`open` or `locked`), `gate_reason`, `task`, `difficulty` | `index` is the larger of the BFI and BVI rises. Each camera is compared with its own baseline median. After the first second of the hold, the index is the median rise of up to four responsive cameras (rise at least 3%, at least two of them), or of every eligible camera when fewer than two move. `alert` is secondary telemetry: true only when that index is at least `alert_at` (0.10) and contact quality is at least 0.50. It does not unlock the task. `gate` is `open` only during recovery when forehead BFI has returned toward baseline (relative rise under 5%) and contact quality is at least 0.50. Bad contact keeps `gate` `locked`. `task` is `locked`, `advance`, `ease`, `break`, `coach`, or `hold`. `difficulty` is the task step, 1 to 4. `channels` names the cameras in use, for example `BFI L3, L4, R2`. `tau_s` is the recovery time constant in seconds once a decay fit succeeds. A slow tau (18 s or more) coaches a breath and eases the step. Optical heart rate is not an input |
| `phase` | `t`, `session_id`, `phase` (`baseline`, `hold`, `recovery`, `end`), `source` (`manual` or `timer`) | sent by the session/phase logger |
| `session` | `t`, `active`, `session_id`, `subject_id`, `phase`, `phase_t`, `timer_next`, `timer_ends_t`, `loop`, `loop_cue`, `gate`, `difficulty` | sent by the dashboard itself whenever the session changes. `loop` is `off`, `baseline`, `challenge`, `coach`, `continue`, `locked`, `task`, `ease`, or `break`. `gate` is `off`, `open`, or `locked`. `difficulty` is the task step. The recovery gate, not the stress label, unlocks `task` |
| `device` | `t`, `connected`, `console`, `left`, `right`, `scanning`, `sdk_version`, `error` | sent by the dashboard itself for the Open-Motion device. While a scan runs, the dashboard produces `bfi`, `bvi`, and `cq` from the SDK `live` channel using per-camera light and dark DN (the same thresholds as `features/cq_score.py`), not the timestamp-quality flag. It then derives `stress` and optical `hr` |
| `status` | `source`, `connected`, `detail` | the dashboard sends these itself on connect and disconnect. Producers may add detail, e.g. `"right sensor not connected"` |

Unknown types and unknown fields are rejected. To change the contract, edit `dashboard/schema.py` and this file together, with Jahlon (dashboard lane owner).

## Phase markers for other recordings

The phase logger also publishes an LSL stream named **`stress-alert-phases`** (type `Markers`, string samples `<phase>|<session_id>|<source>`, timestamped on the shared clock). Record it next to the Open-Motion stream, for example in LabRecorder, to align any recording to baseline, hold and recovery. Each session also writes `sessions/<session_id>/events.csv` and `meta.json`.

## Example

```json
[
  {"type": "bfi", "t": 1089839.91, "left": [2.1, 2.3, 1.9, 2.0, 2.2, 2.4, 2.0, 1.8], "right": [2.0, 2.2, 1.9, 2.1, 2.2, 2.3, 2.1, 1.9]},
  {"type": "hr", "t": 1089839.91, "source": "optical", "bpm": 71.8},
  {"type": "cq", "t": 1089839.91, "left": 0.92, "right": 0.88}
]
```
