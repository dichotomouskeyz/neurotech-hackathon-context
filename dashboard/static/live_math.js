"use strict";

// Pure helpers for the live dashboard. app.js calls these as liveMath.*.
// Node tests require this file. Keep the rules in sync with dashboard/live_gate.py.

// Long session. Keep these next to session/phase_logger.py LONG_* constants.
const LOOP_DEFAULTS = {
  baseline: 20,
  hold: 0,
  recovery: 20,
  continue_s: 1200,
  cycles: 1,
  recovered_within_pct: 5,
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

// BFI keeps the raw pulse on the trace. The axis follows the slow level of
// the last few seconds, plus the pulse amplitude and a little room, so a band
// that sits near 5 to 7 can move to 6 to 8. It does not lock to one heartbeat
// peak, and it does not keep the whole 30 s of history (that is what left the
// axis wide after the level had already moved). BVI does not use this.
const BFI_BOUND_WINDOW_S = 8;

function levelBounds(values) {
  const sorted = (values || []).filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = quantile(sorted, 0.5);
  let lo = quantile(sorted, 0.02);
  let hi = quantile(sorted, 0.98);
  // A flat stretch still needs a readable span. The pulse path is wider than this.
  if (hi - lo < 0.5) {
    lo = mid - 0.25;
    hi = mid + 0.25;
  }
  const half = Math.max(mid - lo, hi - mid);
  const pad = Math.max(half * 0.15, 0.1);
  return { lo: mid - half - pad, hi: mid + half + pad };
}

function bfiBounds(times, seriesList, origin) {
  const t = times || [];
  if (!t.length) return null;
  const last = t[t.length - 1];
  const start = last - BFI_BOUND_WINDOW_S;
  const picked = [];
  const fallback = [];
  for (const values of seriesList || []) {
    for (let i = 0; i < t.length; i += 1) {
      const value = values ? values[i] : undefined;
      if (!Number.isFinite(value)) continue;
      if (origin != null && t[i] < origin) continue;
      fallback.push(value);
      if (t[i] >= start) picked.push(value);
    }
  }
  return levelBounds(picked.length >= 8 ? picked : fallback);
}

// Scale from the current phase once it has a handful of samples, so a level
// shift at hold does not leave the trace flattened on the baseline axis.
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

function nonNegativeNumber(value, fallback) {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number >= 0 ? number : fallback;
}

function recoveredWithinPct(value, fallback) {
  if (value === "" || value == null) return fallback;
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return fallback;
  return number;
}

function protocolBody(fields, options = {}) {
  const src = fields || {};
  const body = {
    baseline: positiveNumber(src.baseline, LOOP_DEFAULTS.baseline),
    // 0 skips the breath-hold. A blank field is 0, which is that skip.
    hold: nonNegativeNumber(src.hold, LOOP_DEFAULTS.hold),
    recovery: positiveNumber(src.recovery, LOOP_DEFAULTS.recovery),
    continue_s: positiveNumber(src.continue_s, LOOP_DEFAULTS.continue_s),
    cycles: Math.min(10, Math.max(1, Math.round(positiveNumber(src.cycles, LOOP_DEFAULTS.cycles)))),
    recovered_within_pct: recoveredWithinPct(
      src.recovered_within_pct,
      LOOP_DEFAULTS.recovered_within_pct,
    ),
  };
  if (options.closedLoop) {
    body.closed_loop = true;
    body.subject_id = options.subjectId || "";
  }
  if (options.workUntilEnd) body.work_until_end = true;
  return body;
}

function loopTotalSeconds(body) {
  const hold = body.hold > 0 ? body.hold : 0;
  const recovery = body.hold > 0 ? body.recovery : 0;
  return body.baseline + hold + recovery + body.continue_s;
}

function loopButtonLabel(body, options = {}) {
  if (options && options.workUntilEnd) return "Long session (until End)";
  const work = body.continue_s;
  if (work >= 60) {
    const minutes = Math.max(1, Math.round(work / 60));
    return `Long session (${minutes} min work)`;
  }
  return `Closed loop (~${Math.round(loopTotalSeconds(body))}s)`;
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
    if (task === "coach") {
      const why = (stress && stress.gate_reason) || "";
      if (why.includes("bfi") || why === "coach_mean") {
        return { status: "warning", text: "Open, breath", headline: `Step ${step}` };
      }
      return { status: "warning", text: "Open, slow recovery", headline: `Step ${step}` };
    }
    if (task === "break") return { status: "warning", text: "Open, take a break", headline: `Step ${step}` };
    if (task === "ease") return { status: "warning", text: "Open, easing", headline: `Step ${step}` };
    return { status: "good", text: "Perfusion-ready", headline: `Step ${step}` };
  }
  const task = stress && stress.task;
  const reason = (stress && stress.gate_reason) || "";
  if (task === "coach" && reason.includes("bfi")) {
    return { status: "warning", text: "Locked, breath", headline: "Locked" };
  }
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
  BFI_BOUND_WINDOW_S,
  cameraStats,
  yExtent,
  levelBounds,
  bfiBounds,
  traceExtent,
  phaseFraction,
  safeClock,
  protocolBody,
  loopTotalSeconds,
  loopButtonLabel,
  stressState,
  gateState,
  gateReadout,
  recoveryTauText,
  worstCq,
};

if (typeof module === "object" && module.exports) module.exports = liveMath;
globalThis.liveMath = liveMath;
