"use strict";

const WINDOW_S = 30;
const STALE_S = 5;
const CQ_GOOD = 0.7;
const CQ_WEAK = 0.4;
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
  const v = values.filter((x) => x !== null).sort((a, b) => a - b);
  if (!v.length) return [null, null, null];
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  return [mean, quantile(v, 0.25), quantile(v, 0.75)];
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
function updateYRange(buf) {
  const yRange = buf.yRange;
  let lo = Infinity;
  let hi = -Infinity;
  const [loKey, hiKey] = showSpread ? ["lo", "hi"] : ["mean", "mean"];
  for (const side of SIDES) {
    for (const v of buf[side][loKey]) if (v !== null && v < lo) lo = v;
    for (const v of buf[side][hiKey]) if (v !== null && v > hi) hi = v;
  }
  if (!Number.isFinite(lo)) return;
  const pad = Math.max((hi - lo) * 0.08, 0.1);
  const target = { lo: Math.floor((lo - pad) * 2) / 2, hi: Math.ceil((hi + pad) * 2) / 2 };
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

let session = { active: false, phase: null };
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
        { ...axis, size: 44, values: (u, ticks) => ticks.map((v) => v.toFixed(1)) },
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

function renderPhaseTile() {
  const now = sharedNow();
  const tile = $("tile-phase");
  const phase = session.active ? session.phase : null;
  tile.dataset.phase = phase || "";
  $("phase-name").textContent = session.active ? phase || "Ready" : "Idle";
  const running = phase && phase !== "end" && now !== null;
  $("phase-elapsed").textContent = running ? fmtClock(now - session.phase_t) : "";
  const timed = session.timer_next && session.timer_ends_t && now !== null;
  $("phase-next").textContent = timed ? `${session.timer_next} in ${fmtClock(session.timer_ends_t - now)}` : "";
  const progress = timed
    ? Math.min(1, (now - session.phase_t) / (session.timer_ends_t - session.phase_t))
    : 0;
  $("phase-progress").style.width = `${(progress * 100).toFixed(1)}%`;
  $("breath-phase").textContent = $("phase-name").textContent;
  $("breath-clock").textContent = $("phase-elapsed").textContent;
  $("breath-next").textContent = $("phase-next").textContent;
  $("breath-progress").style.strokeDasharray = `${(progress * 100).toFixed(1)} 100`;
  $("breath-progress").style.opacity = progress > 0 ? "1" : "0";
}

// Breathing circle: a slow ambient rise and fall at baseline, held full during the
// breath hold, quicker during recovery. Static when the viewer asks for reduced motion.
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
let breathScale = 0.72;
function breathTarget(seconds) {
  const phase = session.active ? session.phase : null;
  const wave = (period, amp) =>
    reduceMotion.matches ? 0 : amp * Math.sin((2 * Math.PI * seconds) / period);
  if (phase === "baseline") return 0.84 + wave(5, 0.05);
  if (phase === "hold") return 1;
  if (phase === "recovery") return 0.88 + wave(3.5, 0.07);
  return 0.72;
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
  const detail = [
    optical.confidence != null ? `confidence ${fmt(optical.confidence)}` : null,
    optical.window_s != null ? `${Math.round(optical.window_s)} s window` : null,
  ].filter(Boolean).join(" · ");
  $("hr-note").textContent = stale ? `last value ${Math.round(now - optical.t)} s ago` : detail;
}

function cqStatus() {
  if (!latest.cq) return null;
  const worst = Math.min(latest.cq.left, latest.cq.right);
  if (worst >= CQ_GOOD) return ["good", "Good contact"];
  if (worst >= CQ_WEAK) return ["warning", "Weak contact"];
  return ["critical", "Fix sensor coupling"];
}

function renderCqTile() {
  if (!latest.cq) return;
  $("tile-cq").dataset.live = "true";
  for (const side of SIDES) {
    const v = latest.cq[side];
    $(`cq-${side}`).textContent = fmt(v);
    $(`cq-${side}-fill`).style.width = `${Math.round(v * 100)}%`;
  }
  const [status, text] = cqStatus();
  setState($("cq-state"), status, text);
}

function renderStressTile() {
  const s = latest.stress;
  if (!s) return;
  $("tile-stress").dataset.live = "true";
  $("stress-index").textContent = fmt(s.index);
  const cq = cqStatus();
  $("tile-stress").dataset.alert = String(Boolean(s.alert && (!cq || cq[0] === "good")));
  if (cq && cq[0] !== "good") {
    setState($("stress-state"), "warning", "Contact too weak to judge");
  } else if (s.alert) {
    setState($("stress-state"), "critical", s.reason ? `Alert: ${s.reason}` : "Alert");
  } else {
    setState($("stress-state"), "good", "No alert");
  }
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
  const timerRunning = Boolean(session.timer_next);
  const canTime = session.active && (session.phase === null || session.phase === "recovery");
  $("protocol-start").disabled = !canTime || timerRunning;
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
$("protocol-form").addEventListener("submit", (e) => {
  e.preventDefault();
  post("/api/protocol/start", {
    baseline: Number($("dur-baseline").value),
    hold: Number($("dur-hold").value),
    recovery: Number($("dur-recovery").value),
    cycles: Number($("cycles").value),
  });
});
$("protocol-stop").addEventListener("click", () => post("/api/protocol/stop"));

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
      break;
    case "hr":
      latest.hr[frame.source] = frame;
      renderHrTile();
      break;
    case "cq":
      latest.cq = frame;
      renderCqTile();
      renderStressTile();
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
