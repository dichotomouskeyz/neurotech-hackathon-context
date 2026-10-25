"use strict";

// Pure helpers for the live dashboard. app.js calls these as liveMath.*.
// Node tests require this file. Keep the rules in sync with dashboard/live_gate.py.

const LOOP_DEFAULTS = {
  baseline: 15,
  hold: 20,
  recovery: 20,
  continue_s: 5,
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

// Scale from the current phase once it has a handful of samples, so a level
// shift at hold does not leave the pulse flattened on the baseline axis.
function traceExtent(times, left, right, origin) {
  const picked = [];
  const take = (series) => {
    for (let i = 0; i < times.length; i += 1) {
      const value = series[i];
      if ((origin == null || times[i] >= origin) && Number.isFinite(value)) picked.push(value);
    }
  };
  take(left || []);
  take(right || []);
  const fallback = [...(left || []), ...(right || [])].filter((value) => Number.isFinite(value));
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
function stressState(stress, phase) {
  const reason = (stress && stress.reason) || "";
  const alert = Boolean(stress && stress.alert);
  if (reason.includes("poor_coupling")) return { status: "warning", text: "Poor contact, alert off" };
  if (alert) return { status: "critical", text: "Elevated vs baseline" };
  if (phase === "hold" || phase === "recovery") {
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
  cameraStats,
  yExtent,
  traceExtent,
  phaseFraction,
  safeClock,
  protocolBody,
  loopTotalSeconds,
  stressState,
};

if (typeof module === "object" && module.exports) module.exports = liveMath;
globalThis.liveMath = liveMath;
