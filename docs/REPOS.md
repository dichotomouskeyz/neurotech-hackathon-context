# Openwater repos by track

From `gh repo list OpenwaterHealth` on 2026-10-24. Dates are last push. Bold repos are the most likely starting points.

## Open-Motion (tracks 1, 2, 3, 4, 7)

| Repo | Lang | Last push | What it is |
| :- | :- | :- | :- |
| **openmotion-sdk** | Python | 10-23 | Hardware I/O library for Open-Motion. Tracks 1 to 4. |
| **openmotion-bloodflow-app** | Python | 10-23 | Research desktop app. Reference for tracks 2 and 3. |
| openmotion-test-app | QML | 10-16 | Hardware validation app |
| openmotion-console-fw | C | 10-22 | Console power and control PCB firmware. Track 7. |
| openmotion-sensor-fw | C | 10-16 | Sensor module firmware. Track 7. |
| openmotion-camera-fpga | Verilog | 10-09 | Camera module FPGA. Track 7. |
| openmotion-safety-fpga, -seed-fpga, -ta-fpga | Verilog | 10-09 | Console 3.0 FPGA projects. Track 7. |
| openmotion-electrical | | 10-09 | PCB layouts. Track 7. |
| openmotion-mechanical | | 10-09 | CAD and enclosures. Track 7. |

## Open-LIFU (tracks 4, 5, 6, 7)

| Repo | Lang | Last push | What it is |
| :- | :- | :- | :- |
| **openlifu-python** | Python | 10-19 | Focused ultrasound toolbox. Tracks 4 and 5. |
| **openlifu-sample-database** | | 10-22 | Transducer configs, protocols, sample data. Tracks 5 and 6. |
| **SlicerOpenLIFU** | Python | 10-09 | 3D Slicer extension. Tracks 5 and 6. |
| openlifu-desktop-application | Python | 10-12 | Planning and control GUI. Track 5 UX. |
| openlifu-sdk | Python | 10-23 | Hardware I/O library. Track 4. |
| openlifu-verification-tank | Python | 10-19 | Tank control software. Track 5 tank tie-in. |
| openwater-reference-meshes | | 10-09 | Skull, head, brain meshes. Tracks 5 and 6. |
| OpenLIFU-3DScanner | Kotlin | 10-09 | Mesh capture app for transducer localization. Track 6. |
| AutoFiducialContest | Python | 10-09 | Spring 2025 landmark contest data and stubs. Track 6. |
| openlifu-closed-loop-eeg | HTML | 10-09 | Closed-loop EEG work. Possible Wildcard bridge to the EEG devices. |
| openlifu-test-app, openlifu-test-scripts | QML, Python | 10-23 | Hardware validation |
| openlifu-transmitter-fw, openlifu-console-fw | C | 10-23, 10-16 | Firmware. Track 7. |
| openlifu-electrical, openlifu-mechanical | | 10-09 | PCB and mechanical. Track 7. |

## Shared

| Repo | What it is |
| :- | :- |
| openwater-docs | Platform documentation (pushed today) |
| openwater-phantoms | Phantom designs. Track 7. |
| awesome-openwater | Curated resources and papers |
| openwater-community, openwater-commons | Developer portal, governance, roadmap |

Older or out-of-scope repos (oncolysis, neuromod MATLAB, USTX boards, bootloaders, regulatory, patents) are left out.
