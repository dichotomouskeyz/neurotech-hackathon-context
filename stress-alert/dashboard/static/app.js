"use strict";

const WINDOW_S = 30;
const CAMERAS = 8;

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Per-side ring of BFI samples: t[] plus one array per camera.
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

function makeChart(el) {
  const camStroke = css("--muted");
  const series = [{}];
  for (let i = 0; i < CAMERAS; i += 1) {
    series.push({ label: `cam ${i + 1}`, stroke: camStroke, width: 1, alpha: 0.35, show: true });
  }
  series.push({ label: "mean", stroke: css("--accent"), width: 2 });
  return new uPlot(
    {
      width: el.clientWidth,
      height: 220,
      legend: { show: false },
      cursor: { show: false },
      scales: { x: { time: false } },
      axes: [
        { stroke: css("--muted"), grid: { stroke: css("--line") }, label: "seconds", values: (u, ticks) => ticks.map((v) => v.toFixed(0)) },
        { stroke: css("--muted"), grid: { stroke: css("--line") }, label: "BFI" },
      ],
      series,
    },
    [[], ...Array.from({ length: CAMERAS + 1 }, () => [])],
    el,
  );
}

const charts = {
  left: makeChart(document.getElementById("chart-left")),
  right: makeChart(document.getElementById("chart-right")),
};

function chartData(series) {
  const last = series.t.length ? series.t[series.t.length - 1] : 0;
  return [series.t.map((t) => t - last), ...series.cams, series.mean];
}

// Frames per second per side, for the panel headers.
const counts = { left: 0, right: 0 };
setInterval(() => {
  for (const side of ["left", "right"]) {
    document.getElementById(`rate-${side}`).textContent = counts[side] ? `${counts[side]} Hz` : "";
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

function setChip(id, label, on) {
  let chip = document.getElementById(id);
  if (!chip) {
    chip = document.createElement("span");
    chip.className = "chip";
    chip.id = id;
    document.getElementById("sources").appendChild(chip);
  }
  chip.textContent = label;
  chip.dataset.state = on ? "on" : "off";
}

function markLive(panelId) {
  document.getElementById(panelId).classList.add("live");
}

function handle(frame) {
  switch (frame.type) {
    case "bfi":
      pushHemo(bfi.left, frame.t, frame.left);
      pushHemo(bfi.right, frame.t, frame.right);
      counts.left += 1;
      counts.right += 1;
      markLive("panel-bfi-left");
      markLive("panel-bfi-right");
      dirty = true;
      break;
    case "status":
      setChip(`chip-src-${frame.source}`, frame.source, frame.connected);
      break;
    default:
      break; // bvi, hr, cq, stress, phase: rendered in later steps
  }
}

function connect(delay = 500) {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => { setChip("chip-socket", "dashboard socket", true); delay = 500; };
  ws.onmessage = (event) => { JSON.parse(event.data).forEach(handle); };
  ws.onclose = () => {
    setChip("chip-socket", "dashboard socket", false);
    setTimeout(() => connect(Math.min(delay * 2, 5000)), delay);
  };
}
connect();

document.getElementById("pause").addEventListener("click", (event) => {
  paused = !paused;
  event.currentTarget.setAttribute("aria-pressed", String(paused));
  event.currentTarget.textContent = paused ? "Resume view" : "Pause view";
});

window.addEventListener("resize", () => {
  for (const side of ["left", "right"]) {
    const el = document.getElementById(`chart-${side}`);
    charts[side].setSize({ width: el.clientWidth, height: 220 });
  }
});
