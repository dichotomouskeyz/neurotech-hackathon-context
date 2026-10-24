# Dashboard message contract

Producers (ingest, features, the phase logger) send JSON to the dashboard over a WebSocket. The dashboard validates every frame and rebroadcasts valid ones to browsers. The source of truth is `dashboard/schema.py`. This file is the readable copy.

## Connecting

```
ws://<dashboard-host>:8765/ws/ingest?source=<your-name>
```

- `source` names your producer (for example `omotion`, `mentalab`, `features`). The dashboard shows a status chip for it, green while connected.
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
| `hr` | `t`, `source` (`optical` or `ecg`), `bpm` | 0 < bpm < 300 |
| `cq` | `t`, `left`, `right` | contact quality, 0 to 1 |
| `stress` | `t`, `index`, `recovery_score` (optional), `alert` (bool), `reason` | the dashboard only shows an alert when contact quality passes its threshold |
| `phase` | `t`, `session_id`, `phase` (`baseline`, `hold`, `recovery`, `end`), `source` (`manual` or `timer`) | sent by the session/phase logger |
| `session` | `t`, `active`, `session_id`, `subject_id`, `phase`, `phase_t`, `timer_next`, `timer_ends_t` | sent by the dashboard itself whenever the session changes |
| `status` | `source`, `connected`, `detail` | the dashboard sends these itself on connect and disconnect. Producers may add detail, e.g. `"no ECG signal"` |

Unknown types and unknown fields are rejected. To change the contract, edit `dashboard/schema.py` and this file together, with Jahlon (dashboard lane owner).

## Phase markers for other recordings

The phase logger also publishes an LSL stream named **`stress-alert-phases`** (type `Markers`, string samples `<phase>|<session_id>|<source>`, timestamped on the shared clock). Record it next to the ECG and Open-Motion streams, for example in LabRecorder, to align any recording to baseline, hold and recovery. Each session also writes `sessions/<session_id>/events.csv` and `meta.json`.

## Example

```json
[
  {"type": "bfi", "t": 1089839.91, "left": [2.1, 2.3, 1.9, 2.0, 2.2, 2.4, 2.0, 1.8], "right": [2.0, 2.2, 1.9, 2.1, 2.2, 2.3, 2.1, 1.9]},
  {"type": "hr", "t": 1089839.91, "source": "optical", "bpm": 71.8},
  {"type": "cq", "t": 1089839.91, "left": 0.92, "right": 0.88}
]
```
