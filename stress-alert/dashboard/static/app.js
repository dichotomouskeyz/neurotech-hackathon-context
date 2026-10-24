"use strict";

const WINDOW_S = 30;
const CAMERAS = 8;
const NEXT = {
  null: ["baseline", "end"],
  baseline: ["hold", "end"],
  hold: ["recovery", "end"],
  recovery: ["baseline", "end"],
  end: [],
};

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Shared clock: server t (LSL local_clock) mapped onto performance.now().
let clockOffset = null;
const sharedNow = () => (clockOffset === null ? null : performance.now() / 1000 + clockOffset);
async function syncClock() {
  const sent = performance.now();
  const { t } = await (await fetch("/api/clock")).json();
  const rtt = (performance.now() - sent) / 1000;
  clockOffset = t + rtt / 2 - performance.now() / 1000;
}

// Signal buffers -----------------------------------------------------------

function makeSeries() {
  return { t: [], cams: Array.from({ length: CAMERAS }, () => []), mean: [] };
}
const bfi = { left: makeSeries(), right: makeSeries() };
let paused = false;
let dirty = false;

function pushHemo(series, t, values) {
  series.t.push(t);
  let sum = 0;
  let n = 0;
  values.forEach((v, i) => {
    series.cams[i].push(v);
    if (v !== null) { sum += v; n += 1; }
  });
  series.mean.push(n ? sum / n : null);
  const cutoff = t - WINDOW_S;
  let drop = 0;
  while (drop < series.t.length && series.t[drop] < cutoff) drop += 1;
  if (drop) {
    series.t.splice(0, drop);
    series.mean.splice(0, drop);
    series.cams.forEach((c) => c.splice(0, drop));
  }
}

// Phase state --------------------------------------------------------------

let session = { active: false, phase: null };
let phases = []; // phase frames for the current session, oldest first

function phaseRgb(phase) {
  return css(`--phase-${phase}`);
}

// Shade each phase interval behind the traces and label it at the top.
function phaseBands(u, series) {
  if (!phases.length || !series.t.length) return;
  const last = series.t[series.t.length - 1];
  const { ctx } = u;
  const { top, height } = u.bbox;
  ctx.save();
  ctx.font = `${11 * devicePixelRatio}px system-ui, sans-serif`;
  phases.forEach((p, i) => {
    if (p.phase === "end") return;
    const end = i + 1 < phases.length ? phases[i + 1].t : last;
    const x0 = u.valToPos(Math.max(p.t - last, -WINDOW_S), "x", true);
    const x1 = u.valToPos(Math.min(end - last, 0), "x", true);
    if (x1 <= x0) return;
    const rgb = phaseRgb(p.phase);
    ctx.fillStyle = `rgba(${rgb}, 0.12)`;
    ctx.fillRect(x0, top, x1 - x0, height);
    const pad = 4 * devicePixelRatio;
    if (ctx.measureText(p.phase).width + 2 * pad <= x1 - x0) {
      ctx.fillStyle = `rgba(${rgb}, 0.9)`;
      ctx.fillText(p.phase, x0 + pad, top + 13 * devicePixelRatio);
    }
  });
  ctx.restore();
}

// Charts -------------------------------------------------------------------

function makeChart(el, side) {
  const series = [{}];
  for (let i = 0; i < CAMERAS; i += 1) {
    series.push({ label: `cam ${i + 1}`, stroke: css("--muted"), width: 1, alpha: 0.35 });
  }
  series.push({ label: "mean", stroke: css("--accent"), width: 2 });
  const axis = { stroke: css("--muted"), grid: { stroke: css("--line") } };
  return new uPlot(
    {
      width: el.clientWidth,
      height: 220,
      legend: { show: false },
      cursor: { show: false },
      scales: { x: { time: false } },
      axes: [
        { ...axis, label: "seconds", values: (u, ticks) => ticks.map((v) => v.toFixed(0)) },
        { ...axis, label: "BFI" },
      ],
      series,
      hooks: { drawClear: [(u) => phaseBands(u, bfi[side])] },
    },
    [[], ...Array.from({ length: CAMERAS + 1 }, () => [])],
    el,
  );
}

const charts = {
  left: makeChart($("chart-left"), "left"),
  right: makeChart($("chart-right"), "right"),
};

function chartData(series) {
  const last = series.t.length ? series.t[series.t.length - 1] : 0;
  return [series.t.map((t) => t - last), ...series.cams, series.mean];
}

const counts = { left: 0, right: 0 };
setInterval(() => {
  for (const side of ["left", "right"]) {
    $(`rate-${side}`).textContent = counts[side] ? `${counts[side]} Hz` : "";
    counts[side] = 0;
  }
}, 1000);

function draw() {
  if (dirty && !paused) {
    charts.left.setData(chartData(bfi.left));
    charts.right.setData(chartData(bfi.right));
    dirty = false;
  }
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

// Session panel ------------------------------------------------------------

const fmt = (s) => {
  const sec = Math.max(0, Math.round(s));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
};

function renderSession() {
  $("session-id").textContent = session.active ? session.session_id : "no session";
  $("session-start").disabled = session.active;
  $("session-stop").disabled = !session.active;
  $("subject").disabled = session.active;
  $("notes").disabled = session.active;

  const allowed = session.active ? NEXT[session.phase] : [];
  document.querySelectorAll(".phase-buttons button").forEach((b) => {
    b.disabled = !allowed.includes(b.dataset.phase);
  });

  const timerRunning = session.timer_next !== null && session.timer_next !== undefined;
  const canTime = session.active && (session.phase === null || session.phase === "recovery");
  $("protocol-start").disabled = !canTime || timerRunning;
  $("protocol-stop").disabled = !timerRunning;
  document.querySelectorAll("#protocol-form input").forEach((i) => { i.disabled = timerRunning; });

  $("phase-now").dataset.phase = session.phase || "";
  $("phase-name").textContent = session.active ? session.phase || "ready" : "idle";
  tick();
}

function tick() {
  const now = sharedNow();
  const running = session.active && session.phase && session.phase !== "end" && now !== null;
  $("phase-elapsed").textContent = running ? fmt(now - session.phase_t) : "";
  const timed = session.timer_next && session.timer_ends_t && now !== null;
  $("phase-next").textContent = timed
    ? `${session.timer_next} in ${fmt(session.timer_ends_t - now)}`
    : "";
}
setInterval(tick, 250);

function renderEvents() {
  const list = $("events");
  list.replaceChildren(
    ...phases.slice(-8).map((p) => {
      const li = document.createElement("li");
      const start = phases[0].t;
      li.textContent = `${fmt(p.t - start)} ${p.phase}${p.source === "timer" ? " (timer)" : ""}`;
      li.style.borderColor = p.phase === "end" ? "" : `rgb(${phaseRgb(p.phase)})`;
      return li;
    }),
  );
}

async function post(url, body) {
  $("session-error").textContent = "";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? data.detail[0].msg : data.detail;
    $("session-error").textContent = detail || `request failed (${res.status})`;
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

// Stream -------------------------------------------------------------------

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
      pushHemo(bfi.left, frame.t, frame.left);
      pushHemo(bfi.right, frame.t, frame.right);
      counts.left += 1;
      counts.right += 1;
      $("panel-bfi-left").classList.add("live");
      $("panel-bfi-right").classList.add("live");
      dirty = true;
      break;
    case "session":
      // Keep the last session's bands after it stops; clear them when a new one starts.
      if (frame.session_id && frame.session_id !== session.session_id) phases = [];
      session = frame;
      renderSession();
      renderEvents();
      dirty = true;
      break;
    case "phase":
      if (frame.session_id !== session.session_id) break;
      if (!phases.some((p) => p.t === frame.t)) phases.push(frame);
      renderEvents();
      dirty = true;
      break;
    case "status":
      setChip(`chip-src-${frame.source.replace(/\W+/g, "-")}`, frame.source, frame.connected, frame.detail);
      break;
    default:
      break; // bvi, hr, cq, stress: rendered in milestone 3
  }
}

function connect(delay = 500) {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => {
    setChip("chip-socket", "dashboard socket", true);
    delay = 500;
    syncClock();
  };
  ws.onmessage = (event) => { JSON.parse(event.data).forEach(handle); };
  ws.onclose = () => {
    setChip("chip-socket", "dashboard socket", false);
    setTimeout(() => connect(Math.min(delay * 2, 5000)), delay);
  };
}
connect();
renderSession();

$("pause").addEventListener("click", (event) => {
  paused = !paused;
  event.currentTarget.setAttribute("aria-pressed", String(paused));
  event.currentTarget.textContent = paused ? "Resume view" : "Pause view";
});

window.addEventListener("resize", () => {
  for (const side of ["left", "right"]) {
    charts[side].setSize({ width: $(`chart-${side}`).clientWidth, height: 220 });
  }
});
