# Devpost Project Submission Draft

**Project Title**: Stress-Alert: CQ-Gated Optical Cerebrovascular Reactivity on Open-Motion

**Event**: UC Berkeley Neurotechnology Hackathon (October 24 to 25, 2026)  
**Sponsor**: Openwater  
**Platform**: Open-Motion (Diffuse Optical Blood Flow Station)  
**Team**: Jahlon Burruss, Raymond Mak, Liam Lenh, Teammates  

---

## Elevator Pitch

A real-time optical stress and recovery monitoring system built on Open-Motion, featuring a contact-quality (CQ) gate that suppresses false alarms from motion artifacts and computes exponential recovery time-constants for research.

---

## Research Scope Notice

This project is a research engineering demonstration created during a 24-hour hackathon. The recorded metrics, stress index, and recovery parameters do not constitute clinical screening, diagnosis, medical monitoring, therapy, or treatment. Openwater approved self-testing of Open-Motion by team members for this project; all participant recordings remain local and private.

---

## Inspiration and Prompt

**Prompt**: *How can neurotechnology expand human cognitive potential?*

Expanding cognitive potential requires an objective, non-invasive window into cerebral autoregulation and autonomic stress. When individuals encounter acute cognitive or physiological load, cerebral hemodynamics and autonomic state shift rapidly. However, non-invasive optical neurotechnology in naturalistic settings faces a fundamental obstacle: sensor slippage, facial muscle movement, and hair obstruction create optical artifacts that closely mimic physiological surges.

Existing platforms often overclaim, treating motion artifacts as physiological events. We set out to build an artifact-robust pipeline on Open-Motion that:
1. Tracks forehead blood flow index (BFI), blood volume index (BVI), and optical heart rate at 40 Hz.
2. Strictly gates stress alerts on per-camera contact quality (CQ).
3. Models post-stress hemodynamic return using an exponential recovery time-constant (tau).

---

## What It Does

The system executes a standardized 3-minute breath-hold protocol and streams data to a synchronized dashboard:

1. **Phase 1: Baseline (60 seconds)**
   - The participant rests quietly with normal tidal breathing.
   - The pipeline continuously evaluates optical coupling and establishes a robust resting baseline for forehead BFI and heart rate.

2. **Phase 2: Breath-Hold Stress Induction (20 to 40 seconds, default 30 seconds)**
   - Voluntary end-tidal breath-holding induces transient hypercapnia (arterial PaCO2 elevation).
   - In response, cerebral vasculature dilates, driving a 20% to 50% elevation in forehead BFI.
   - If contact quality remains above threshold (CQ >= 0.50), the system validates the surge as physiological and triggers an elevated stress alert.

3. **Phase 3: Contact-Quality Gate (Artifact Suppression)**
   - If the participant moves, frowns, or the headband slips, optical quality drops.
   - The CQ gate suppresses the stress alert, labeling the frame `poor_coupling: CQ < 0.50` rather than false stress.

4. **Phase 4: Hemodynamic Recovery Kinetics (90 seconds)**
   - The participant resumes normal breathing.
   - Forehead BFI decays back toward baseline.
   - The alert engine fits an exponential decay function to compute the recovery time-constant tau (seconds) and fraction recovered.

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

## Future Closed-Loop Research (Not Part of This Build)

In future research outside the hackathon, this non-invasive optical stress and recovery index could serve as the sensing arm in a closed-loop neuromodulation system. Specifically:
- Openwater's Open-LIFU (Low-Intensity Focused Ultrasound) platform could deliver targeted neuromodulation to the hypothalamic-pituitary-adrenal (HPA) axis or vagal pathways when sustained stress is detected.
- Real-time recovery kinetics ($\tau$) could provide quantitative feedback on whether ultrasound stimulation accelerates autonomic recovery.
- For this weekend's build, we deliberately kept the system strictly empirical and observational, proving the sensing and artifact-rejection pipeline first.

---

## Built With

- **Hardware**: Openwater Open-Motion Optical Station
- **Languages & Frameworks**: Python 3.12, FastAPI, WebSockets, uPlot, Pydantic, NumPy, SciPy
- **Protocols & Standards**: Lab Streaming Layer (LSL), JSON frame messaging
