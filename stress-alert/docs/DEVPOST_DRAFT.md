# Devpost Project Submission Draft

**Project Title**: Perfusion-Ready Gate: Task Unlock from Open-Motion Forehead BFI

**Event**: UC Berkeley Neurotechnology Hackathon (October 24 to 25, 2026)  
**Sponsor**: Openwater  
**Platform**: Open-Motion (Diffuse Optical Blood Flow Station)  
**Team**: Jahlon Burruss, Raymond Mak, Liam Lenh, Teammates  

---

## Elevator Pitch

A research demo on Open-Motion. A short calibration learns resting forehead blood flow. Then a long work bout, about 20 minutes, unlocks the next step only when BFI has returned and contact quality is good. When flow leaves that baseline and contact is still good, a breath starts on its own. Difficulty, a break, and that breath coach follow BFI, blood volume (BVI), and recovery tau. For research. Not a stress classifier and not a diagnosis.

---

## Research Scope Notice

This project is a research engineering demonstration created during a 24-hour hackathon. The recorded metrics, stress index, and recovery parameters do not constitute clinical screening, diagnosis, medical monitoring, therapy, or treatment. Openwater approved self-testing of Open-Motion by team members for this project; all participant recordings remain local and private.

---

## Inspiration and Prompt

**Prompt**: *How can neurotechnology expand human cognitive potential?*

Expanding cognitive potential needs a control signal for when the next piece of work should start, ease off, or wait. A short baseline sit calibrates resting forehead blood flow. An optional breath-hold shows how that flow returns. The product is what happens after that, while someone is working for a long bout: Open-Motion BFI and BVI decide the next step, and a breath starts when flow leaves the baseline. Contact quality tells us whether that signal is trustworthy.

We built a perfusion-ready gate on that signal:
1. Calibrate. A short baseline learns per-camera resting BFI. A breath-hold and recovery are optional proof. The task stays locked. Optical heart rate stays a side panel and does not drive the loop.
2. Work. The bout defaults to 20 minutes. The next step unlocks only when BFI has returned toward that baseline and contact quality is at least 0.50. Bad contact cannot unlock the step.
3. During that bout, if BFI is off the calibrated baseline and contact is still good, the breath coach starts on its own and stops when flow returns. If BVI is still high, ease the step or ask for a break. If the recovery time constant is slow, coach a breath as well. The policy uses BFI, BVI, and tau, not an EEG-style focus score.

---

## What It Does

The dashboard has two parts. Calibration is a short baseline sit that learns resting forehead BFI. The breath-hold is optional. Work is the application: a long bout gated by the recovery policy, with a breath that starts when flow leaves baseline and contact is good. Demo Mode replays the 16-channel sample scan without a laser, the same feed as `--dev-feed`. It will not start during a live scan.

1. **Calibration**
   - Baseline breathing sets a per-camera BFI and BVI baseline, and only while contact quality is at least 0.50.
   - A gentle breath-hold is the calibration load, not the product. Recovery fits how flow returns.
   - The task stays locked through all three.

2. **Work**
   - The chart is the proof. Flow starts up, as if the person has been working, and the next step stays locked.
   - The gate opens only when forehead BFI is back under 5% of the calibrated baseline and contact quality is still at least 0.50.
   - If contact drops below 0.50, the gate locks even if the flow trace looks recovered.
   - When the gate opens, task difficulty advances one step. While the bout is running, BFI off baseline with contact still at least 0.50 starts the breath coach, and the coach stops when flow returns. If BVI is still elevated, the step eases or the banner asks for a break. If recovery tau is 18 seconds or slower, the step eases and the breath coach runs.
   - A calibration hold that never rises does not pretend the work step unlocked.

---

## System Architecture and Modular Lanes

The team divided development into decoupled lanes operating against a strict schema contract (`stress-alert/dashboard/SCHEMA.md`):

```
+-------------------------------------------------------------+
|                     Participant Sensors                     |
|  - Open-Motion Forehead Headband (16 cameras, 40 Hz BFI/BVI)|
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|               Lane 1: Ingest & Signal Extraction            |
|  - omotion_source.py: CSV replay / live station interface   |
|  - cq_score.py: 16-channel optical contact quality (0 to 1) |
|  - pulse_hr.py: optical HR estimation from BFI residuals    |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|               Lane 4: Alert Math & Protocol (Our Lane)      |
|  - protocol/breathhold.md: standardized 3-phase procedure   |
|  - stress_index.py: CQ-gated stress index & recovery tau    |
|  - Gating: alert = (CQ >= 0.50) and (index >= 10%)        |
|  - Recovery model: exponential decay regression (tau_s)     |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                  Sync & Live Dashboard                      |
|  - Fast API / WebSocket server with Pydantic frame contract |
|  - session/phase_logger.py: automated timer & LSL markers   |
|  - Real-time uPlot browser interface with status strips     |
+-------------------------------------------------------------+
```

---

## Mathematical Formulation

### 1. Stress Index and Contact Quality Gate
For timestamp $t$, camera $i$, its 1 second median $x_i(t)$, its own resting baseline median $b_i$, and contact quality $\text{CQ}(t)$:

$$\Delta_i(t) = \frac{x_i(t) - b_i}{b_i}$$

After the first second of the hold, $S$ is the set of up to four cameras with the largest $\Delta_i$, keeping a camera only when $\Delta_i \ge 0.03$ and at least two cameras clear that floor. If fewer than two do, $S$ is every eligible camera. Eligible cameras have a stable positive baseline. Non-positive samples are left out.

$$\text{index}(t) = \max\left(0, \operatorname{median}_{i \in S} \Delta_i(t)\right)$$

The published index is the larger of the BFI index and the BVI index. Nothing is added on top of the measured rise.

$$\text{alert}(t) = \begin{cases} 
\text{True} & \text{if } \text{CQ}(t) \ge 0.50 \text{ and } \text{index}(t) \ge 0.10 \\
\text{False} & \text{otherwise}
\end{cases}$$

When $\text{CQ}(t) < 0.50$, the system explicitly outputs:
`reason = "poor_coupling: CQ < 0.50"`

### 2. Post-Stress Recovery Time-Constant ($\tau$)
During the 90-second recovery phase, excess blood flow above baseline decays exponentially:

$$y(t) - y_{\text{base}} \approx (y_{\text{peak}} - y_{\text{base}}) \cdot e^{-\frac{t - t_{\text{peak}}}{\tau}}$$

Applying a log transformation:

$$\ln\left(\frac{y(t) - y_{\text{base}}}{y_{\text{peak}} - y_{\text{base}}}\right) \approx -\frac{1}{\tau}(t - t_{\text{peak}})$$

We fit the linear slope $m = -1 / \tau$ via ordinary least squares regression over post-peak recovery points, reporting $\tau = -1 / m$ (in seconds) along with the fit coefficient of determination ($R^2$).

---

## Honest Null Results and Technical Challenges

1. **Motion Artifacts Mimic Blood Flow**:
   Initial testing confirmed that physical head movements create high-amplitude spikes in optical BFI. Relying on BFI alone produced massive false-positive stress alerts. Gating strictly on per-camera contact quality solved this problem.
2. **Non-Monotonic Recovery**:
   When participants swallow or speak during the 90-second recovery phase, the hemodynamic decay curve deviates from pure exponential decay. Instead of forcing a bad fit, our algorithm reports an honest null result (`tau_s = None`, `note = "signal rising rather than recovering"`).
3. **Optical Heart Rate Without a Reference**:
   Optical pulse estimation from BFI residuals requires clean coupling and at least 8 to 10 seconds of steady data. Under motion, the optical estimator returns an honest null. We planned a Mentalab ECG as a reference heart rate, but it did not work at the event, so the optical rate is reported as an unvalidated estimate.

---

## Closed loop in this build

The loop that ships is a task policy, not stimulation and not a diagnosis. Calibration learns the resting signal. Work is where the gate opens: BFI returned and contact quality good. Ultrasound neuromodulation is outside this hackathon build.

For research. The perfusion tile, the recovery time constant, and the task step are engineering readouts. They are not a screening result, a clinical score, or a treatment signal.

---

## Built With

- **Hardware**: Openwater Open-Motion Optical Station
- **Languages & Frameworks**: Python 3.12, FastAPI, WebSockets, uPlot, Pydantic, NumPy, SciPy
- **Protocols & Standards**: Lab Streaming Layer (LSL), JSON frame messaging
