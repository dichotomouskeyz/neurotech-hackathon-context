"use strict";

// Pure helpers for the live dashboard. app.js calls these as liveMath.*.
// Node tests require this file. Keep the rules in sync with dashboard/live_gate.py.

const LOOP_DEFAULTS = {
  baseline: 8,
  hold: 8,
  recovery: 12,
  continue_s: 32,
  cycles: 1,
};

function quantile(sorted, q) {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const next = sorted[base + 1] ?? sorted[base];
  return sorted[base] + (pos - base) * (next - sorted[base]);
}

// Median of the positive cameras when they are the majority. A few dark or
// zero cameras then cannot collapse the side trace. If most cameras are
// non-positive, the median of every finite value is used so a real drop
// still shows.
function cameraStats(values) {
  const finite = [];
  for (const value of values || []) {
    if (typeof value === "number" && Number.isFinite(value)) finite.push(value);
  }
  if (!finite.length) return [null, null, null];
  const positive = finite.filter((value) => value > 0);
  const chosen = positive.length * 2 >= finite.length ? positive : finite;
  chosen.sort((a, b) => a - b);
  return [quantile(chosen, 0.5), quantile(chosen, 0.25), quantile(chosen, 0.75)];
}

function yExtent(values) {
  const sorted = (values || []).filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!sorted.length) return null;
  let lo = quantile(sorted, 0.1);
  let hi = quantile(sorted, 0.9);
  if (hi - lo < 0.3) {
    const mid = quantile(sorted, 0.5);
    lo = mid - 0.15;
    hi = mid + 0.15;
  }
  const pad = Math.max((hi - lo) * 0.08, 0.05);
  return {
    lo: Math.floor((lo - pad) * 2) / 2,
    hi: Math.ceil((hi + pad) * 2) / 2,
  };
}

// Blood flow pulses about once a second. That swing was setting the BFI axis,
// so a small left/right offset sat inside the heartbeat. A 1 s trailing mean
// is what the chart draws and scales. Blood volume does not get this window.
const BFI_DISPLAY_WINDOW_S = 1;

function trailingMean(times, values, windowSec) {
  const n = (times || []).length;
  const out = new Array(n);
  let start = 0;
  let sum = 0;
  let count = 0;
  for (let i = 0; i < n; i += 1) {
    const value = values ? values[i] : undefined;
    if (Number.isFinite(value)) {
      sum += value;
      count += 1;
    }
    const cutoff = times[i] - windowSec;
    while (start < i && times[start] < cutoff) {
      const old = values ? values[start] : undefined;
      if (Number.isFinite(old)) {
        sum -= old;
        count -= 1;
      }
      start += 1;
    }
    out[i] = count ? sum / count : null;
  }
  return out;
}

// Series the chart draws. BFI is the trailing mean, and the first second of
// each side is held back until that mean has a full window, so the left edge
// cannot reopen the axis around one heartbeat. BVI is the raw trace.
function chartView(metric, times, channels, viewSec) {
  const t = times || [];
  const lookback = metric === "bfi" ? BFI_DISPLAY_WINDOW_S : 0;
  const smooth = (values) => {
    const src = values || [];
    return lookback > 0 ? trailingMean(t, src, lookback) : src.slice();
  };
  const sided = {};
  for (const side of ["left", "right"]) {
    const channel = (channels && channels[side]) || {};
    sided[side] = { mean: smooth(channel.mean), lo: smooth(channel.lo), hi: smooth(channel.hi) };
  }
  if (!t.length) return { t: [], left: sided.left, right: sided.right };
  const last = t[t.length - 1];
  const displayStart = Math.max(t[0] + lookback, last - viewSec);
  let i0 = 0;
  while (i0 < t.length && t[i0] < displayStart) i0 += 1;
  const cut = (arr) => arr.slice(i0);
  return {
    t: t.slice(i0),
    left: { mean: cut(sided.left.mean), lo: cut(sided.left.lo), hi: cut(sided.left.hi) },
    right: { mean: cut(sided.right.mean), lo: cut(sided.right.lo), hi: cut(sided.right.hi) },
  };
}

// Scale from the current phase once it has a handful of samples, so a level
// shift at hold does not leave the trace flattened on the baseline axis.
// `extras` are optional series, used for the camera-spread band when it is on.
function traceExtent(times, left, right, origin, extras) {
  const series = [left || [], right || []];
  for (const extra of extras || []) series.push(extra || []);
  const picked = [];
  const fallback = [];
  for (const values of series) {
    for (let i = 0; i < times.length; i += 1) {
      const value = values[i];
      if (!Number.isFinite(value)) continue;
      fallback.push(value);
      if (origin == null || times[i] >= origin) picked.push(value);
    }
  }
  return yExtent(picked.length >= 8 ? picked : fallback);
}

function phaseFraction(now, phaseT, endsT) {
  if (!Number.isFinite(now) || !Number.isFinite(phaseT) || !Number.isFinite(endsT)) return 0;
  const span = endsT - phaseT;
  if (!(span > 0)) return 0;
  const elapsed = now - phaseT;
  if (!Number.isFinite(elapsed) || elapsed < 0) return 0;
  return Math.min(1, elapsed / span);
}

function safeClock(seconds) {
  if (!Number.isFinite(seconds)) return "--";
  const sec = Math.max(0, Math.round(seconds));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

function positiveNumber(value, fallback) {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function protocolBody(fields, options = {}) {
  const src = fields || {};
  const body = {
    baseline: positiveNumber(src.baseline, LOOP_DEFAULTS.baseline),
    hold: positiveNumber(src.hold, LOOP_DEFAULTS.hold),
    recovery: positiveNumber(src.recovery, LOOP_DEFAULTS.recovery),
    continue_s: positiveNumber(src.continue_s, LOOP_DEFAULTS.continue_s),
    cycles: Math.min(10, Math.max(1, Math.round(positiveNumber(src.cycles, LOOP_DEFAULTS.cycles)))),
  };
  if (options.closedLoop) {
    body.closed_loop = true;
    body.subject_id = options.subjectId || "";
  }
  return body;
}

function loopTotalSeconds(body) {
  return body.baseline + body.hold + body.recovery + body.continue_s;
}

// Hold and recovery never keep the baseline subtitle. Poor contact and a real
// alert win over that label.
function finiteCq(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function worstCq(cq) {
  if (!cq) return null;
  const known = ["left", "right"].map((side) => finiteCq(cq[side])).filter((value) => value !== null);
  if (!known.length) return null;
  return Math.min(...known);
}

// Display rule for the recovery gate. Open only when the server says so.
// A missing gate stays locked. If the latest contact score is already under
// 0.50, do not keep an older open decision on screen.
// Fitted recovery time constant only. Missing, non-finite, and boolean values
// stay blank. The phase timer is not a tau.
function recoveryTauText(stress) {
  const tau = stress && stress.tau_s;
  if (typeof tau !== "number" || !Number.isFinite(tau)) return "--";
  return tau.toFixed(1);
}

function gateState(stress, cq) {
  const score = worstCq(cq);
  if (score !== null && score < 0.5) {
    return { status: "critical", text: "Locked, contact", headline: "Locked" };
  }
  const gate = stress && stress.gate;
  if (gate !== "open" && gate !== "locked") {
    return { status: "unknown", text: "Waiting for BFI and contact", headline: "Locked" };
  }
  if (gate === "open") {
    const step = stress.difficulty || 1;
    const task = stress.task || "hold";
    if (task === "coach") return { status: "warning", text: "Open, slow recovery", headline: `Step ${step}` };
    if (task === "break") return { status: "warning", text: "Open, take a break", headline: `Step ${step}` };
    if (task === "ease") return { status: "warning", text: "Open, easing", headline: `Step ${step}` };
    return { status: "good", text: "Perfusion-ready", headline: `Step ${step}` };
  }
  const reason = (stress && stress.gate_reason) || "";
  if (reason.includes("cq") || ((stress && stress.reason) || "").includes("poor_coupling")) {
    return { status: "critical", text: "Locked, contact", headline: "Locked" };
  }
  if (reason.includes("bfi")) return { status: "warning", text: "Locked, BFI", headline: "Locked" };
  return { status: "warning", text: "Locked", headline: "Locked" };
}

function gateReadout(stress, cq) {
  const score = worstCq(cq);
  const cqText = score === null ? "CQ waiting" : `CQ ${score.toFixed(2)}`;
  const state = gateState(stress, cq);
  if (score !== null && score < 0.5) return `Gate locked · contact · ${cqText}`;
  if (!stress || (stress.gate !== "open" && stress.gate !== "locked")) {
    return `Gate waiting · ${cqText}`;
  }
  if (stress.gate === "open") return `Gate open · ${state.headline.toLowerCase()} · ${cqText}`;
  const why = state.text.startsWith("Locked, ") ? state.text.slice("Locked, ".length) : "waiting";
  return `Gate locked · ${why} · ${cqText}`;
}

function stressState(stress, phase) {
  const reason = (stress && stress.reason) || "";
  const alert = Boolean(stress && stress.alert);
  if (reason.includes("poor_coupling")) return { status: "warning", text: "Poor contact, alert off" };
  if (alert) return { status: "critical", text: "Elevated vs baseline" };
  if (phase === "hold" || phase === "recovery" || phase === "work") {
    if (reason.includes("uncalibrated")) return { status: "warning", text: "Needs a baseline" };
    return { status: "good", text: "Near baseline" };
  }
  if (phase === "baseline" || reason.includes("resting baseline")) {
    return { status: "good", text: "Resting baseline" };
  }
  if (reason.includes("uncalibrated") || reason.includes("collecting")) {
    return { status: "warning", text: "Needs a baseline" };
  }
  return { status: "good", text: "Near baseline" };
}

const liveMath = {
  LOOP_DEFAULTS,
  BFI_DISPLAY_WINDOW_S,
  cameraStats,
  yExtent,
  trailingMean,
  chartView,
  traceExtent,
  phaseFraction,
  safeClock,
  protocolBody,
  loopTotalSeconds,
  stressState,
  gateState,
  gateReadout,
  recoveryTauText,
  worstCq,
};

if (typeof module === "object" && module.exports) module.exports = liveMath;
globalThis.liveMath = liveMath;
