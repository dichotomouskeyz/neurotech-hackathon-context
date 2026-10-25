"use strict";

const WINDOW_S = 30;
const STALE_S = 5;
const CQ_GOOD = 0.7;
const CQ_GATE = 0.5;
const CQ_WEAK = 0.4;
const BREATH_IN_S = 4;
const BREATH_OUT_S = 6;
const NEXT = {
  null: ["baseline", "end"],
  baseline: ["hold", "end"],
  hold: ["recovery", "end"],
  recovery: ["baseline", "end"],
  end: [],
};

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmtClock = (s) => {
  const sec = Math.max(0, Math.round(s));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
};
const fmt = (v, digits = 2) => (v === null || v === undefined || Number.isNaN(v) ? "--" : v.toFixed(digits));

// Shared clock: server t (LSL local_clock) mapped onto performance.now().
let clockOffset = null;
const sharedNow = () => (clockOffset === null ? null : performance.now() / 1000 + clockOffset);
async function syncClock() {
  const sent = performance.now();
  const { t } = await (await fetch("/api/clock")).json();
  clockOffset = t + (performance.now() - sent) / 2000 - performance.now() / 1000;
}

// Hemodynamic buffers, one per metric (BFI, BVI): per side, the camera mean and
// the spread of the middle 50% of cameras (25th to 75th percentile). Min/max is
// dominated by one outlier camera in real data, so the interquartile band is the
// honest spread.

const SIDES = ["left", "right"];
const METRICS = ["bfi", "bvi"];
const makeBuffer = () => ({
  t: [],
  left: { mean: [], lo: [], hi: [] },
  right: { mean: [], lo: [], hi: [] },
  yRange: { lo: null, hi: null, shrinkSince: null },
});
const bufs = { bfi: makeBuffer(), bvi: makeBuffer() };
let paused = false;
let dirty = false;
let framesThisSecond = 0;

function quantile(sorted, q) {
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const next = sorted[base + 1] ?? sorted[base];
  return sorted[base] + (pos - base) * (next - sorted[base]);
}

function summarize(values) {
  return liveMath.cameraStats(values);
}

function pushHemo(buf, frame) {
  buf.t.push(frame.t);
  for (const side of SIDES) {
    const [mean, lo, hi] = summarize(frame[side]);
    buf[side].mean.push(mean);
    buf[side].lo.push(lo);
    buf[side].hi.push(hi);
  }
  let drop = 0;
  while (drop < buf.t.length && buf.t[drop] < frame.t - WINDOW_S) drop += 1;
  if (drop) {
    buf.t.splice(0, drop);
    for (const side of SIDES) for (const k of ["mean", "lo", "hi"]) buf[side][k].splice(0, drop);
  }
}

// Y range that grows at once but only shrinks after it has been too wide for a while,
// so the traces do not jump on every frame.
function scaleOrigin() {
  if (!session.active) return null;
  if (!["baseline", "hold", "recovery"].includes(session.phase)) return null;
  return Number.isFinite(session.phase_t) ? session.phase_t : null;
}

function updateYRange(buf) {
  const yRange = buf.yRange;
  const origin = scaleOrigin();
  // Refit when the phase changes. A hold that sits lower than baseline would
  // otherwise stay squashed on the baseline scale for the whole window.
  if (yRange.origin !== origin) {
    yRange.lo = null;
    yRange.hi = null;
    yRange.shrinkSince = null;
    yRange.origin = origin;
  }
  const target = liveMath.traceExtent(buf.t, buf.left.mean, buf.right.mean, origin);
  if (!target) return;
  if (yRange.lo === null || target.lo < yRange.lo || target.hi > yRange.hi) {
    yRange.lo = Math.min(target.lo, yRange.lo ?? target.lo);
    yRange.hi = Math.max(target.hi, yRange.hi ?? target.hi);
    yRange.shrinkSince = null;
  } else if (target.lo > yRange.lo || target.hi < yRange.hi) {
    yRange.shrinkSince ??= performance.now();
    if (performance.now() - yRange.shrinkSince > 8000) {
      Object.assign(yRange, { lo: target.lo, hi: target.hi, shrinkSince: null });
    }
  } else {
    yRange.shrinkSince = null;
  }
}

// Session and phase state ------------------------------------------------

let session = { active: false, phase: null, loop: "off", loop_cue: "" };
let phases = [];

function phaseBands(u, buf) {
  if (!phases.length || !buf.t.length) return;
  const last = buf.t[buf.t.length - 1];
  const { ctx } = u;
  const { top, height } = u.bbox;
  const dpr = devicePixelRatio;
  const fills = { hold: css("--phase-hold"), recovery: css("--phase-recovery") };
  ctx.save();
  ctx.font = `500 ${11 * dpr}px ${css("--font-sans")}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  phases.forEach((p, i) => {
    if (p.phase === "end") return;
    const end = i + 1 < phases.length ? phases[i + 1].t : last;
    if (end - last < -WINDOW_S) return;
    const x0 = u.valToPos(Math.max(p.t - last, -WINDOW_S), "x", true);
    const x1 = u.valToPos(Math.min(end - last, 0), "x", true);
    if (x1 <= x0) return;
    if (fills[p.phase]) {
      ctx.fillStyle = fills[p.phase];
      ctx.fillRect(x0, top, x1 - x0, height);
    }
    if (p.t - last >= -WINDOW_S) {
      ctx.fillStyle = css("--phase-edge");
      ctx.fillRect(Math.round(x0), top, dpr, height);
    }
    const pad = 6 * dpr;
    if (ctx.measureText(p.phase).width + 2 * pad <= x1 - x0) {
      ctx.fillStyle = css("--ink-muted");
      ctx.fillText(p.phase, x0 + pad, top + 14 * dpr);
    }
  });
  ctx.restore();
}

// Name each side at the right end of its line, in text ink beside a colored dot.
function directLabels(u) {
  const n = u.data[0].length;
  if (!n) return;
  const { ctx } = u;
  const dpr = devicePixelRatio;
  const labels = [[1, "Left", "--series-left"], [4, "Right", "--series-right"]]
    .map(([idx, label, color]) => {
      const v = u.data[idx][n - 1];
      return v === null || v === undefined ? null : { label, color, y: u.valToPos(v, "y", true) };
    })
    .filter(Boolean)
    .sort((a, b) => a.y - b.y);
  // Keep the two labels at least one line apart, centered on their true positions.
  const gap = 14 * dpr;
  if (labels.length === 2 && labels[1].y - labels[0].y < gap) {
    const mid = (labels[0].y + labels[1].y) / 2;
    labels[0].y = mid - gap / 2;
    labels[1].y = mid + gap / 2;
  }
  ctx.save();
  ctx.font = `500 ${11 * dpr}px ${css("--font-sans")}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  labels.forEach(({ label, color, y }) => {
    const x = u.bbox.left + u.bbox.width + 12 * dpr;
    ctx.fillStyle = css(color);
    ctx.beginPath();
    ctx.arc(x + 3 * dpr, y, 3 * dpr, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = css("--ink-2");
    ctx.fillText(label, x + 10 * dpr, y);
  });
  ctx.restore();
}

// Chart --------------------------------------------------------------------

const charts = {};
let hoverIdx = null;
// The camera spread is mostly the cameras' different analog gains, so it is an
// operator view, off by default.
let showSpread = false;

const chartHeight = () => (document.body.dataset.view === "present" ? 300 : 240);

function makeChart(metric) {
  const buf = bufs[metric];
  const el = $(`chart-${metric}`);
  el.replaceChildren();
  const axis = {
    stroke: css("--ink-muted"),
    grid: { stroke: css("--hairline"), width: 1 },
    ticks: { show: false },
    font: `12px ${css("--font-mono")}`,
  };
  const envelope = { stroke: "transparent", width: 0, points: { show: false } };
  charts[metric] = new uPlot(
    {
      width: el.clientWidth,
      height: chartHeight(),
      padding: [8, 60, 0, 0],
      legend: { show: false },
      cursor: {
        y: false,
        points: { size: 7, width: 2 },
        drag: { x: false, y: false },
        sync: { key: "hemo" },
      },
      scales: {
        x: { time: false, range: [-WINDOW_S, 0] },
        y: { range: () => (buf.yRange.lo === null ? [0, 1] : [buf.yRange.lo, buf.yRange.hi]) },
      },
      axes: [
        { ...axis, values: (u, ticks) => ticks.map((v) => (v === 0 ? "now" : `${v}s`)) },
        { ...axis, size: 44, values: (u, ticks) => ticks.map((v) => (Number.isFinite(v) ? v.toFixed(1) : "")) },
      ],
      series: [
        {},
        { label: "Left", stroke: css("--series-left"), width: 2 },
        { label: "Left max", ...envelope },
        { label: "Left min", ...envelope },
        { label: "Right", stroke: css("--series-right"), width: 2 },
        { label: "Right max", ...envelope },
        { label: "Right min", ...envelope },
      ],
      bands: showSpread
        ? [
            { series: [2, 3], fill: css("--band-left") },
            { series: [5, 6], fill: css("--band-right") },
          ]
        : [],
      hooks: {
        drawClear: [(u) => phaseBands(u, buf)],
        draw: [directLabels],
        setCursor: [(u) => { hoverIdx = u.cursor.idx ?? null; renderLegends(); }],
      },
    },
    chartData(buf),
    el,
  );
}

function chartData(buf) {
  const last = buf.t.length ? buf.t[buf.t.length - 1] : 0;
  return [
    buf.t.map((t) => t - last),
    buf.left.mean, buf.left.hi, buf.left.lo,
    buf.right.mean, buf.right.hi, buf.right.lo,
  ];
}

// Legend readouts follow the synced crosshair, or show the latest sample.
function renderLegends() {
  for (const metric of METRICS) {
    const buf = bufs[metric];
    const n = buf.t.length;
    const i = hoverIdx ?? n - 1;
    $(`val-left-${metric}`).textContent = n ? fmt(buf.left.mean[i]) : "--";
    $(`val-right-${metric}`).textContent = n ? fmt(buf.right.mean[i]) : "--";
  }
}

function resizeCharts() {
  for (const metric of METRICS) {
    charts[metric].setSize({ width: $(`chart-${metric}`).clientWidth, height: chartHeight() });
  }
}

function draw() {
  animateBreath();
  if (dirty && !paused) {
    for (const metric of METRICS) {
      updateYRange(bufs[metric]);
      charts[metric].setData(chartData(bufs[metric]));
    }
    if (hoverIdx === null) renderLegends();
    dirty = false;
  }
  requestAnimationFrame(draw);
}

setInterval(() => {
  $("rate").textContent = framesThisSecond ? `${framesThisSecond} Hz` : "";
  framesThisSecond = 0;
}, 1000);

// Status strip -----------------------------------------------------------

const latest = { hr: {}, cq: null, stress: null };

function setState(el, status, text) {
  el.dataset.status = status;
  el.textContent = text;
}

function breathCycle(seconds) {
  const period = BREATH_IN_S + BREATH_OUT_S;
  const x = ((seconds % period) + period) % period;
  if (x < BREATH_IN_S) {
    return { word: "Inhale", scale: 0.7 + 0.3 * (x / BREATH_IN_S), progress: x / period };
  }
  const y = (x - BREATH_IN_S) / BREATH_OUT_S;
  return { word: "Exhale", scale: 1 - 0.3 * y, progress: x / period };
}

function renderPhaseTile() {
  const now = sharedNow();
  const tile = $("tile-phase");
  const phase = session.active ? session.phase : null;
  const loop = session.loop || "off";
  tile.dataset.phase = phase || "";
  document.body.dataset.loop = loop;
  $("phase-name").textContent = session.active ? phase || "Ready" : "Idle";
  const running = phase && phase !== "end" && now !== null && Number.isFinite(session.phase_t);
  const elapsed = running ? now - session.phase_t : null;
  $("phase-elapsed").textContent = elapsed !== null && Number.isFinite(elapsed) ? liveMath.safeClock(elapsed) : "";
  const timed = Boolean(session.timer_next) && Number.isFinite(session.timer_ends_t) && Number.isFinite(now);
  const remaining = timed ? session.timer_ends_t - now : null;
  let nextText = "";
  if (timed && Number.isFinite(remaining)) {
    nextText = `${session.timer_next} in ${liveMath.safeClock(remaining)}`;
    if (loop === "coach") nextText += " · or when it settles";
  }
  $("phase-next").textContent = nextText;
  let progress = timed
    ? liveMath.phaseFraction(now, session.phase_t, session.timer_ends_t)
    : 0;
  const guided = loop === "coach" ? breathCycle(performance.now() / 1000) : null;
  if (guided) progress = guided.progress;
  $("phase-progress").style.width = `${(progress * 100).toFixed(1)}%`;
  $("breath-phase").textContent = guided ? guided.word : $("phase-name").textContent;
  $("breath-clock").textContent = guided ? "Breathe" : $("phase-elapsed").textContent;
  $("breath-next").textContent = guided ? "Follow the circle" : $("phase-next").textContent;
  $("breath-progress").style.strokeDasharray = `${(progress * 100).toFixed(1)} 100`;
  $("breath-progress").style.opacity = progress > 0 ? "1" : "0";
  renderCoach(guided);
}

// Breathing circle: a slow ambient rise and fall at baseline, held full during the
// breath hold, quicker during recovery. Static when the viewer asks for reduced motion.
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
let breathScale = 0.72;
function breathTarget(seconds) {
  const phase = session.active ? session.phase : null;
  const loop = session.loop || "off";
  const wave = (period, amp) =>
    reduceMotion.matches ? 0 : amp * Math.sin((2 * Math.PI * seconds) / period);
  if (loop === "coach") return breathCycle(seconds).scale;
  if (loop === "challenge" || phase === "hold") return 1;
  if (loop === "baseline" || phase === "baseline") return 0.84 + wave(5, 0.05);
  if (loop === "continue" || phase === "recovery") return 0.88 + wave(3.5, 0.07);
  return 0.72;
}

function renderCoach(guided) {
  const loop = session.loop || "off";
  const el = $("coach");
  el.dataset.mode = loop;
  el.hidden = loop === "off";
  $("coach-cue").textContent = session.loop_cue || "";
  $("coach-step").textContent = loop === "coach" ? (guided ? guided.word : "") : "";
  const kicker = {
    baseline: "Baseline",
    challenge: "Breath-hold",
    coach: "Pause",
    continue: "Continue",
  };
  $("coach-kicker").textContent = kicker[loop] || "Closed loop";
}
function animateBreath() {
  if (document.body.dataset.view !== "present") return;
  const target = breathTarget(performance.now() / 1000);
  breathScale += (target - breathScale) * (reduceMotion.matches ? 1 : 0.06);
  $("breath-core").style.transform = `scale(${breathScale.toFixed(4)})`;
}

function renderHrTile() {
  const { optical } = latest.hr;
  const now = sharedNow();
  $("tile-hr").dataset.live = String(Boolean(optical));
  if (!optical) return;
  $("hr-optical").textContent = Math.round(optical.bpm);
  const stale = now !== null && now - optical.t >= STALE_S;
  $("hr-note").textContent = stale ? `last value ${Math.round(now - optical.t)} s ago` : "";
}

function finiteCq(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function cqStatus() {
  if (!latest.cq) return null;
  const scores = SIDES.map((side) => finiteCq(latest.cq[side]));
  const known = scores.filter((v) => v !== null);
  if (!known.length) return ["unknown", "Contact unknown"];
  const worst = Math.min(...known);
  const missing = scores.some((v) => v === null);
  if (worst >= CQ_GOOD) {
    return missing ? ["warning", "One side has no contact score"] : ["good", "Good contact"];
  }
  // 0.50 is the live-gate threshold. The weaker band is display only.
  if (worst >= CQ_GATE) return ["warning", "Contact ok to score"];
  if (worst >= CQ_WEAK) return ["warning", "Weak contact"];
  return ["critical", "Fix sensor coupling"];
}

function renderCqTile() {
  if (!latest.cq) return;
  const scores = SIDES.map((side) => finiteCq(latest.cq[side]));
  if (scores.every((v) => v === null)) {
    $("tile-cq").dataset.live = "false";
    for (const side of SIDES) {
      $(`cq-${side}`).textContent = "--";
      $(`cq-${side}-fill`).style.width = "0%";
    }
    setState($("cq-state"), "unknown", "Contact unknown");
    return;
  }
  $("tile-cq").dataset.live = "true";
  SIDES.forEach((side, i) => {
    const v = scores[i];
    if (v === null) {
      $(`cq-${side}`).textContent = "--";
      $(`cq-${side}-fill`).style.width = "0%";
    } else {
      $(`cq-${side}`).textContent = fmt(v);
      $(`cq-${side}-fill`).style.width = `${Math.round(v * 100)}%`;
    }
  });
  const [status, text] = cqStatus();
  setState($("cq-state"), status, text);
}

function renderStressTile() {
  const s = latest.stress;
  if (!s) return;
  const reason = s.reason || "";
  const uncalibrated = reason.includes("uncalibrated") || reason.includes("collecting");
  $("tile-stress").dataset.live = "true";
  // The server already gates alert on contact quality. Do not require a
  // stricter "good" band here, or a real elevation is hidden.
  $("tile-stress").dataset.alert = String(Boolean(s.alert));
  const pct = Number.isFinite(s.index) ? `${Math.round(s.index * 100)}%` : "--";
  $("stress-index").textContent = uncalibrated ? "--" : pct;
  const phase = session.active ? session.phase : null;
  const label = liveMath.stressState(s, phase);
  setState($("stress-state"), label.status, label.text);
  const parts = [];
  if (!uncalibrated && reason && !reason.startsWith("resting baseline")) parts.push(reason);
  if (s.channels) parts.push(`using ${s.channels}`);
  if (Number.isFinite(s.alert_at)) parts.push(`alert at ${Math.round(s.alert_at * 100)}%`);
  if (Number.isFinite(s.tau_s)) parts.push(`recovery tau ${Math.round(s.tau_s)} s`);
  if (typeof s.recovery_score === "number" && Number.isFinite(s.recovery_score)) {
    parts.push(`${Math.round(s.recovery_score * 100)}% returned`);
  }
  $("stress-detail").textContent = parts.join(". ");
}

setInterval(() => { renderPhaseTile(); renderHrTile(); }, 250);

// Operator controls --------------------------------------------------------

function renderControls() {
  $("session-id").textContent = session.active ? session.session_id : "no session";
  $("session-start").disabled = session.active;
  $("session-stop").disabled = !session.active;
  $("subject").disabled = session.active;
  $("notes").disabled = session.active;
  const allowed = session.active ? NEXT[session.phase] : [];
  document.querySelectorAll(".phase-buttons button").forEach((b) => {
    b.disabled = !allowed.includes(b.dataset.phase);
  });
  const timerRunning = Boolean(session.timer_next) || ["baseline", "challenge", "coach", "continue"].includes(session.loop);
  const idlePhase = !session.active || session.phase === null || session.phase === "recovery" || session.phase === "end";
  const canTime = session.active && (session.phase === null || session.phase === "recovery");
  $("protocol-start").disabled = !canTime || timerRunning;
  $("loop-start").disabled = !idlePhase || timerRunning;
  $("protocol-stop").disabled = !timerRunning;
  document.querySelectorAll("#protocol-form input").forEach((i) => { i.disabled = timerRunning; });
}

function renderEvents() {
  const start = phases.length ? phases[0].t : 0;
  $("events").replaceChildren(
    ...phases.slice(-8).map((p) => {
      const li = document.createElement("li");
      li.dataset.phase = p.phase;
      li.textContent = `${fmtClock(p.t - start)} ${p.phase}${p.source === "timer" ? " · timer" : ""}`;
      return li;
    }),
  );
}

async function post(url, body, errorId = "session-error") {
  $(errorId).textContent = "";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? data.detail[0].msg : data.detail;
    $(errorId).textContent = detail || `Request failed (${res.status})`;
  }
}

$("session-form").addEventListener("submit", (e) => {
  e.preventDefault();
  post("/api/session/start", { subject_id: $("subject").value, notes: $("notes").value });
});
$("session-stop").addEventListener("click", () => post("/api/session/stop"));
document.querySelectorAll(".phase-buttons button").forEach((b) => {
  b.addEventListener("click", () => post("/api/phase", { phase: b.dataset.phase }));
});
function readProtocolFields() {
  return {
    baseline: $("dur-baseline").value,
    hold: $("dur-hold").value,
    recovery: $("dur-recovery").value,
    continue_s: $("dur-continue").value,
    cycles: $("cycles").value,
  };
}

function refreshLoopButton() {
  const body = liveMath.protocolBody(readProtocolFields());
  const total = Math.round(liveMath.loopTotalSeconds(body));
  $("loop-start").textContent = `Closed loop (~${total}s)`;
}

$("protocol-form").addEventListener("submit", (e) => {
  e.preventDefault();
  post("/api/protocol/start", liveMath.protocolBody(readProtocolFields()));
});
$("protocol-stop").addEventListener("click", () => post("/api/protocol/stop"));
$("loop-start").addEventListener("click", () => {
  post("/api/protocol/start", liveMath.protocolBody(readProtocolFields(), {
    closedLoop: true,
    subjectId: $("subject").value,
  }));
});
$("protocol-form").addEventListener("input", refreshLoopButton);
refreshLoopButton();

// Open-Motion device -------------------------------------------------------

let device = { connected: false, console: false, left: false, right: false, scanning: false };

function setPart(id, label, known, ok) {
  const el = $(id);
  if (!known) {
    delete el.dataset.status;
    el.textContent = label;
    return;
  }
  setState(el, ok ? "good" : "critical", `${label} ${ok ? "connected" : "not found"}`);
}

function renderDevice() {
  const d = device;
  setPart("dev-console", "Console", d.connected, d.console);
  setPart("dev-left", "Left sensor", d.connected && d.console, d.left);
  setPart("dev-right", "Right sensor", d.connected && d.console, d.right);
  $("device-sdk").textContent = d.sdk_version ? `SDK ${d.sdk_version}` : "";
  $("device-error").textContent = d.error || "";
  $("device-connect").textContent = d.connected ? "Search again" : "Connect device";
  $("device-disconnect").disabled = !d.connected;
  $("scan-start").disabled = !d.connected || !d.console || !(d.left || d.right) || d.scanning;
  $("scan-stop").disabled = !d.scanning;
  const ready = d.connected && d.console && (d.left || d.right);
  setChip("chip-device", d.scanning ? "open-motion scanning" : "open-motion", ready, d.error);
}

async function deviceAction(path, button) {
  button.disabled = true;
  const label = button.textContent;
  if (path === "connect") button.textContent = "Searching…";
  try {
    await post(`/api/device/${path}`, {}, "device-error");
  } finally {
    button.textContent = label;
    button.disabled = false;
    renderDevice();
  }
}

$("device-connect").addEventListener("click", (e) => deviceAction("connect", e.currentTarget));
$("device-disconnect").addEventListener("click", (e) => deviceAction("disconnect", e.currentTarget));
$("scan-start").addEventListener("click", (e) => deviceAction("scan/start", e.currentTarget));
$("scan-stop").addEventListener("click", (e) => deviceAction("scan/stop", e.currentTarget));

// View: operator or present ----------------------------------------------

function setView(view) {
  document.body.dataset.view = view;
  document.querySelectorAll(".segmented button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.view === view));
  });
  try { localStorage.setItem("stress-alert:view", view); } catch { /* storage unavailable */ }
  if (charts.bfi) resizeCharts();
}
document.querySelectorAll(".segmented button").forEach((b) => {
  b.addEventListener("click", () => setView(b.dataset.view));
});

// Stream -----------------------------------------------------------------

function setChip(id, label, on, detail) {
  let chip = $(id);
  if (!chip) {
    chip = document.createElement("span");
    chip.className = "chip";
    chip.id = id;
    $("sources").appendChild(chip);
  }
  chip.textContent = label;
  chip.title = detail || "";
  chip.dataset.state = on ? "on" : "off";
}

function handle(frame) {
  switch (frame.type) {
    case "bfi":
    case "bvi":
      pushHemo(bufs[frame.type], frame);
      if (frame.type === "bfi") framesThisSecond += 1;
      $(`card-${frame.type}`).dataset.live = "true";
      dirty = true;
      if (brainHeatmap) {
        brainHeatmap.update(frame);
        const cardH = $("card-heatmap");
        if (cardH && cardH.dataset.live !== "true") {
          cardH.dataset.live = "true";
          const s = $("heatmap-status-text");
          if (s) s.textContent = "Live Stream (40 Hz)";
        }
      }
      break;
    case "hr":
      latest.hr[frame.source] = frame;
      renderHrTile();
      break;
    case "cq":
      latest.cq = frame;
      renderCqTile();
      renderStressTile();
      if (brainHeatmap) brainHeatmap.update(frame);
      break;
    case "stress":
      latest.stress = frame;
      renderStressTile();
      break;
    case "session":
      // Keep the last session's bands after it stops; clear them when a new one starts.
      if (frame.session_id && frame.session_id !== session.session_id) phases = [];
      session = frame;
      renderControls();
      renderPhaseTile();
      renderStressTile();
      renderEvents();
      dirty = true;
      break;
    case "phase":
      if (frame.session_id !== session.session_id) break;
      if (!phases.some((p) => p.t === frame.t)) phases.push(frame);
      renderEvents();
      dirty = true;
      break;
    case "device":
      device = frame;
      renderDevice();
      break;
    case "status":
      setChip(`chip-src-${frame.source.replace(/\W+/g, "-")}`, frame.source, frame.connected, frame.detail);
      break;
    default:
      break;
  }
}

function connect(delay = 500) {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => {
    setChip("chip-socket", "dashboard", true);
    delay = 500;
    syncClock();
  };
  ws.onmessage = (event) => { JSON.parse(event.data).forEach(handle); };
  ws.onclose = () => {
    setChip("chip-socket", "dashboard", false);
    setTimeout(() => connect(Math.min(delay * 2, 5000)), delay);
  };
}

// Start --------------------------------------------------------------------

let initialView = new URLSearchParams(location.search).get("view");
if (!initialView) {
  try { initialView = localStorage.getItem("stress-alert:view"); } catch { initialView = null; }
}
setView(initialView === "present" ? "present" : "operator");
METRICS.forEach(makeChart);
renderControls();
renderDevice();
renderPhaseTile();
connect();
requestAnimationFrame(draw);

// Brain Heatmap Setup
let brainHeatmap = null;
const heatmapCanvas = $("heatmap-canvas");
if (heatmapCanvas && typeof BrainHeatmap !== "undefined") {
  const COLORBAR_GRADIENTS = {
    turbo: "linear-gradient(to top, #30123b, #4145ab, #4675ed, #39a2fc, #1bcfd4, #24eca6, #61fc4c, #a4fc3b, #d1e834, #f3c63a, #fe9b2d, #f36315, #d93806, #b11902, #7a0402)",
    viridis: "linear-gradient(to top, #440154, #482777, #3f4a8a, #31678e, #26838f, #1f9d8a, #6cce5a, #b6de2b, #fee825)",
    coolwarm: "linear-gradient(to top, #3b4cc0, #8cb2e9, #f2f2f2, #f49a7b, #b40426)",
  };

  const updateColorbarGradient = (cm) => {
    const cb = $("heatmap-colorbar");
    if (cb && COLORBAR_GRADIENTS[cm]) {
      cb.style.background = COLORBAR_GRADIENTS[cm];
    }
  };

  brainHeatmap = new BrainHeatmap(heatmapCanvas, {
    container: $("heatmap-container"),
    tooltipEl: $("heatmap-tooltip"),
    onStatsUpdate: (stats) => {
      const elLeft = $("heatmap-stat-left");
      const elRight = $("heatmap-stat-right");
      const elAsym = $("heatmap-stat-asym");
      const elAsymDesc = $("heatmap-stat-asym-desc");
      const cbMax = $("cb-max");
      const cbMid = $("cb-mid");
      const cbMin = $("cb-min");
      const cbUnit = $("cb-unit");

      if (elLeft) elLeft.textContent = fmt(stats.meanL);
      if (elRight) elRight.textContent = fmt(stats.meanR);
      if (elAsym) {
        elAsym.textContent = stats.asym !== null ? `${stats.asym > 0 ? "+" : ""}${stats.asym.toFixed(1)}%` : "--";
      }
      if (elAsymDesc) {
        elAsymDesc.textContent = stats.asym !== null
          ? (stats.asym > 2.5 ? "Right Dominant" : (stats.asym < -2.5 ? "Left Dominant" : "Symmetric (Balanced)"))
          : "R vs L asymmetry";
      }
      if (cbMax) cbMax.textContent = fmt(stats.scaleMax, 1);
      if (cbMid) cbMid.textContent = fmt((stats.scaleMin + stats.scaleMax) / 2, 1);
      if (cbMin) cbMin.textContent = fmt(stats.scaleMin, 1);
      if (cbUnit) {
        cbUnit.textContent = stats.metric === "asym" ? "% Asym" : (stats.metric === "bfi" ? "BFI Index" : "BVI Index");
      }
    },
  });

  updateColorbarGradient("turbo");

  // Projection buttons
  const viewAxial = $("btn-view-axial");
  const viewFrontal = $("btn-view-frontal");
  if (viewAxial && viewFrontal) {
    viewAxial.addEventListener("click", () => {
      viewAxial.classList.add("active");
      viewAxial.setAttribute("aria-pressed", "true");
      viewFrontal.classList.remove("active");
      viewFrontal.setAttribute("aria-pressed", "false");
      brainHeatmap.setProjection("axial");
    });
    viewFrontal.addEventListener("click", () => {
      viewFrontal.classList.add("active");
      viewFrontal.setAttribute("aria-pressed", "true");
      viewAxial.classList.remove("active");
      viewAxial.setAttribute("aria-pressed", "false");
      brainHeatmap.setProjection("frontal");
    });
  }

  // Metric buttons
  const metricBtns = [
    { id: "btn-metric-bfi", metric: "bfi" },
    { id: "btn-metric-bvi", metric: "bvi" },
    { id: "btn-metric-asym", metric: "asym" },
  ];
  metricBtns.forEach(({ id, metric }) => {
    const btn = $(id);
    if (!btn) return;
    btn.addEventListener("click", () => {
      metricBtns.forEach((m) => {
        const b = $(m.id);
        if (b) {
          b.classList.toggle("active", m.metric === metric);
          b.setAttribute("aria-pressed", String(m.metric === metric));
        }
      });
      brainHeatmap.setMetric(metric);
      const sel = $("heatmap-colormap");
      if (sel) {
        sel.value = brainHeatmap.colormap;
        updateColorbarGradient(brainHeatmap.colormap);
      }
    });
  });

  // Colormap select
  const colormapSelect = $("heatmap-colormap");
  if (colormapSelect) {
    colormapSelect.addEventListener("change", (e) => {
      brainHeatmap.setColormap(e.target.value);
      updateColorbarGradient(e.target.value);
    });
  }

  // Toggles
  const showOptodesToggle = $("heatmap-show-optodes");
  if (showOptodesToggle) {
    showOptodesToggle.addEventListener("change", (e) => {
      brainHeatmap.setShowOptodes(e.target.checked);
    });
  }

  const autoscaleToggle = $("heatmap-autoscale");
  if (autoscaleToggle) {
    autoscaleToggle.addEventListener("change", (e) => {
      brainHeatmap.setAutoscale(e.target.checked);
    });
  }

  // Demo simulation mode
  let demoInterval = null;
  let demoT = 0;
  const demoBtn = $("btn-heatmap-demo");
  if (demoBtn) {
    const BASE_L = [3.4, 2.4, 1.3, 0.4, 0.3, 1.4, 2.5, 3.3];
    const BASE_R = [3.5, 2.6, 1.3, 0.5, 0.4, 1.4, 3.5, 4.6];
    const BVI_L = [5.6, 6.0, 6.1, 5.0, 5.6, 6.8, 7.0, 5.8];
    const BVI_R = [5.6, 6.7, 6.9, 7.1, 6.7, 6.7, 6.3, 6.4];

    demoBtn.addEventListener("click", () => {
      if (demoInterval) {
        clearInterval(demoInterval);
        demoInterval = null;
        demoBtn.classList.remove("active");
        demoBtn.textContent = "Demo Mode";
        const statusText = $("heatmap-status-text");
        if (statusText) statusText.textContent = "Waiting for data";
      } else {
        demoBtn.classList.add("active");
        demoBtn.textContent = "Stop Demo";
        const statusText = $("heatmap-status-text");
        if (statusText) statusText.textContent = "Simulated Demo (40 Hz)";
        const cardH = $("card-heatmap");
        if (cardH) cardH.dataset.live = "true";
        const cardBfi = $("card-bfi");
        if (cardBfi) cardBfi.dataset.live = "true";
        const cardBvi = $("card-bvi");
        if (cardBvi) cardBvi.dataset.live = "true";

        demoInterval = setInterval(() => {
          demoT += 0.025; // 40 Hz
          const pulse = 0.28 * Math.sin(2.0 * Math.PI * 1.2 * demoT);
          const resp = 0.18 * Math.sin(2.0 * Math.PI * 0.2 * demoT);
          const asymWave = 0.45 * Math.sin(2.0 * Math.PI * 0.1 * demoT);

          const leftBfi = BASE_L.map((b) => Math.max(0.05, b + pulse + (Math.random() - 0.5) * 0.08));
          const rightBfi = BASE_R.map((b) => Math.max(0.05, b + pulse + asymWave + (Math.random() - 0.5) * 0.08));

          const leftBvi = BVI_L.map((b) => b + resp + (Math.random() - 0.5) * 0.05);
          const rightBvi = BVI_R.map((b) => b + resp + (Math.random() - 0.5) * 0.05);

          const now = sharedNow() || (performance.now() / 1000);
          handle({ type: "bfi", t: now, left: leftBfi, right: rightBfi });
          handle({ type: "bvi", t: now, left: leftBvi, right: rightBvi });
          // Demo mode has no contact signal. Do not publish a fake CQ.
          handle({ type: "hr", t: now, source: "optical", bpm: 72 + Math.sin(demoT * 0.1) * 3 });
        }, 25);
      }
    });
  }
}

$("spread").addEventListener("change", (event) => {
  showSpread = event.currentTarget.checked;
  for (const metric of METRICS) {
    Object.assign(bufs[metric].yRange, { lo: null, hi: null, shrinkSince: null });
    updateYRange(bufs[metric]);
    makeChart(metric);
  }
});

$("pause").addEventListener("click", (event) => {
  paused = !paused;
  event.currentTarget.setAttribute("aria-pressed", String(paused));
  event.currentTarget.textContent = paused ? "Resume" : "Pause";
});
window.addEventListener("resize", resizeCharts);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  METRICS.forEach(makeChart);
  dirty = true;
});
