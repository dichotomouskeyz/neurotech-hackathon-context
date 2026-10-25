# Devpost Project Submission Draft

**Project Title**: Perfusion-Ready Gate: Task Unlock from Open-Motion Forehead BFI

**Event**: UC Berkeley Neurotechnology Hackathon (October 24 to 25, 2026)  
**Sponsor**: Openwater  
**Platform**: Open-Motion (Diffuse Optical Blood Flow Station)  
**Team**: Jahlon Burruss, Raymond Mak, Liam Lenh, Teammates  

---

## Elevator Pitch

A research demo on Open-Motion. A short task stays locked until forehead blood flow (BFI) returns toward baseline and contact quality is good. Difficulty, a break, and a breath coach then follow BFI, blood volume (BVI), and the recovery time constant. Same loop shape as an adaptive focus product, with optical perfusion as the control signal. For research. Not a stress classifier and not a diagnosis.

---

## Research Scope Notice

This project is a research engineering demonstration created during a 24-hour hackathon. The recorded metrics, stress index, and recovery parameters do not constitute clinical screening, diagnosis, medical monitoring, therapy, or treatment. Openwater approved self-testing of Open-Motion by team members for this project; all participant recordings remain local and private.

---

## Inspiration and Prompt

**Prompt**: *How can neurotechnology expand human cognitive potential?*

Expanding cognitive potential needs a control signal for when the next piece of work should start, ease off, or wait. Forehead blood flow and blood volume from Open-Motion move with a breath-hold and then return. Contact quality tells us whether that return is trustworthy.

We built a perfusion-ready gate on that signal:
1. Track forehead BFI and BVI at 40 Hz. Optical heart rate stays a side panel and does not drive the loop.
2. Keep the next task step locked until BFI has returned toward baseline and contact quality is at least 0.50. Bad contact cannot unlock the step.
3. Once the gate is open, step difficulty up. If BVI is still high, ease the step or ask for a break. If the recovery time constant is slow, coach a breath. The policy uses BFI, BVI, and tau, not an EEG-style focus score.

---

## What It Does

The dashboard runs a breath-hold as the load, then a recovery gate that controls a short adaptive task. Demo Mode plays the same policy on a simulated recovery without a laser. Its contact scores stay below 1.00, and Demo Mode will not start during a live scan.

1. **Baseline**
   - Resting breathing sets a per-camera BFI and BVI baseline, and only while contact quality is at least 0.50.
   - The task stays locked.

2. **Breath-hold load**
   - A gentle breath-hold is the physiological load. Forehead BFI rises.
   - The gate stays locked while flow is up. A secondary perfusion tile can show the rise. That tile does not unlock the task.

3. **Recovery gate**
   - The participant breathes with the on-screen coach.
   - The gate opens only when forehead BFI is back under 5% of baseline and contact quality is still at least 0.50.
   - If contact drops below 0.50, the gate locks even if the flow trace looks recovered.

4. **Adaptive step**
   - When the gate opens, task difficulty advances one step.
   - If BVI is still elevated, the step eases or the banner asks for a break.
   - If the fitted recovery time constant is 18 seconds or slower, the step eases and the breath coach runs.
   - A hold that never rises does not pretend the gate unlocked.

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
|  - Gating: alert = (CQ >= 0.50) and (delta_BFI >= 20%)     |
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
For timestamp $t$, current blood flow metric $x(t)$, resting baseline $x_{\text{base}}$, and contact quality $\text{CQ}(t)$:

$$\Delta_{\text{rel}}(t) = \frac{x(t) - x_{\text{base}}}{x_{\text{base}}}$$

$$\text{index}(t) = \max\left(0, \Delta_{\text{rel}}(t)\right)$$

$$\text{alert}(t) = \begin{cases} 
\text{True} & \text{if } \text{CQ}(t) \ge 0.50 \text{ and } \text{index}(t) \ge 0.20 \\
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

The loop that ships is a task policy, not stimulation and not a diagnosis. Demo Mode and the live scan share one gate: BFI returned and contact quality good. Ultrasound neuromodulation is outside this hackathon build.

For research. The perfusion tile, the recovery time constant, and the task step are engineering readouts. They are not a screening result, a clinical score, or a treatment signal.

---

## Built With

- **Hardware**: Openwater Open-Motion Optical Station
- **Languages & Frameworks**: Python 3.12, FastAPI, WebSockets, uPlot, Pydantic, NumPy, SciPy
- **Protocols & Standards**: Lab Streaming Layer (LSL), JSON frame messaging
