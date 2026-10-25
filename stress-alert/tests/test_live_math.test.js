const assert = require("node:assert/strict");
const test = require("node:test");

const liveMath = require("../dashboard/static/live_math.js");

test("protocol defaults sum to one minute and closed loop sends the flag", () => {
  const body = liveMath.protocolBody({});
  assert.deepEqual(body, {
    baseline: 8,
    hold: 8,
    recovery: 12,
    continue_s: 32,
    cycles: 1,
  });
  assert.equal(liveMath.loopTotalSeconds(body), 60);
  const empty = liveMath.protocolBody({ baseline: "", hold: "0", recovery: "nope" });
  assert.equal(empty.baseline, 8);
  assert.equal(empty.hold, 8);
  assert.equal(empty.recovery, 12);
  const loop = liveMath.protocolBody({ baseline: "15", hold: "20" }, {
    closedLoop: true,
    subjectId: "jb",
  });
  assert.equal(loop.closed_loop, true);
  assert.equal(loop.subject_id, "jb");
  assert.equal(liveMath.loopTotalSeconds(loop), 79);
});

test("phase progress and clocks stay finite when the timer is missing", () => {
  assert.equal(liveMath.phaseFraction(null, 10, 20), 0);
  assert.equal(liveMath.phaseFraction(undefined, 10, 20), 0);
  assert.equal(liveMath.phaseFraction(Number.NaN, 10, 20), 0);
  assert.equal(liveMath.phaseFraction(15, null, 20), 0);
  assert.equal(liveMath.phaseFraction(15, 10, 10), 0);
  assert.equal(liveMath.phaseFraction(15, 10, 20), 0.5);
  assert.equal(liveMath.phaseFraction(30, 10, 20), 1);
  assert.equal(liveMath.safeClock(Number.NaN), "--");
  assert.equal(liveMath.safeClock(65), "1:05");
});

test("hold never keeps the resting baseline subtitle", () => {
  const stuck = liveMath.stressState({ reason: "resting baseline", alert: false }, "hold");
  assert.equal(stuck.text, "Near baseline");
  const poor = liveMath.stressState({ reason: "poor_coupling: CQ 0.20 < 0.50" }, "hold");
  assert.equal(poor.text, "Poor contact, alert off");
  const up = liveMath.stressState({ reason: "elevated_stress", alert: true }, "recovery");
  assert.equal(up.text, "Elevated vs baseline");
  const rest = liveMath.stressState({ reason: "resting baseline" }, "baseline");
  assert.equal(rest.text, "Resting baseline");
});

test("recovery gate stays locked until the server opens it", () => {
  const waiting = liveMath.gateState(null);
  assert.equal(waiting.headline, "Locked");
  const contact = liveMath.gateState({ gate: "locked", gate_reason: "locked_cq", reason: "poor_coupling" });
  assert.equal(contact.status, "critical");
  assert.equal(contact.headline, "Locked");
  const flow = liveMath.gateState({ gate: "locked", gate_reason: "locked_bfi" });
  assert.equal(flow.text, "Locked, BFI");
  const open = liveMath.gateState({ gate: "open", difficulty: 2, task: "advance" });
  assert.equal(open.status, "good");
  assert.equal(open.headline, "Step 2");
  const coach = liveMath.gateState({ gate: "open", difficulty: 1, task: "coach" });
  assert.equal(coach.status, "warning");
  const readout = liveMath.gateReadout(
    { gate: "open", difficulty: 2, task: "advance" },
    { left: 0.76, right: 0.74 },
  );
  assert.equal(readout, "Gate open · step 2 · CQ 0.74");
  const blocked = liveMath.gateReadout(
    { gate: "locked", gate_reason: "locked_cq", reason: "poor_coupling" },
    { left: 0.32, right: 0.4 },
  );
  assert.equal(blocked, "Gate locked · contact · CQ 0.32");
  assert.equal(liveMath.gateReadout({ gate: "locked", gate_reason: "locked_bfi" }, { left: 1, right: 0.8 }).includes("1.00"), false);
  const staleOpen = liveMath.gateState({ gate: "open", difficulty: 2, task: "advance" }, { left: 0.32, right: 0.4 });
  assert.equal(staleOpen.headline, "Locked");
  assert.equal(staleOpen.status, "critical");
  assert.equal(
    liveMath.gateReadout({ gate: "open", difficulty: 2, task: "advance" }, { left: 0.32, right: 0.4 }),
    "Gate locked · contact · CQ 0.32",
  );
});

test("recovery tau readout is the fitted number or a blank", () => {
  assert.equal(liveMath.recoveryTauText(null), "--");
  assert.equal(liveMath.recoveryTauText({}), "--");
  assert.equal(liveMath.recoveryTauText({ tau_s: null }), "--");
  assert.equal(liveMath.recoveryTauText({ tau_s: Number.NaN }), "--");
  assert.equal(liveMath.recoveryTauText({ tau_s: 4.46 }), "4.5");
});

test("chart scale ignores a minority of zeros and a baseline level shift", () => {
  const [mid] = liveMath.cameraStats([0, 0, 2, 2.2, 2.4, 2.1, 1.9, 2]);
  assert.ok(mid > 1.5);
  const extent = liveMath.yExtent([2, 2.1, 2, 2.2, 1.9, 2, 2.1, 2, 2, 40]);
  assert.ok(extent.hi < 10);
  const times = [0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17];
  const left = [8, 8, 8, 8, 8, 8, 8, 8, 2, 2.1, 1.9, 2, 2.2, 2, 2.1, 1.8];
  const phase = liveMath.traceExtent(times, left, left, 10);
  assert.ok(phase.hi < 4);
  assert.ok(phase.lo < 2.5);
});

test("BFI chart scale follows the slow left/right offset, not the heartbeat", () => {
  const hz = 40;
  const dur = 12;
  const times = [];
  const left = [];
  const right = [];
  const lo = [];
  const hi = [];
  for (let i = 0; i < hz * dur; i += 1) {
    const time = i / hz;
    times.push(time);
    const pulse = Math.sin((2 * Math.PI * 1.1 * time));
    left.push(5.2 + pulse);
    right.push(5.9 + 0.9 * pulse);
    lo.push(4.0 + 0.2 * pulse);
    hi.push(7.2 + 0.2 * pulse);
  }
  const raw = liveMath.traceExtent(times, left, right, null);
  const view = liveMath.chartView("bfi", times, {
    left: { mean: left, lo, hi },
    right: { mean: right, lo, hi },
  }, 30);
  assert.ok(view.t.length > 0);
  assert.ok(view.t[0] >= liveMath.BFI_DISPLAY_WINDOW_S - 1e-9);
  const fit = liveMath.traceExtent(view.t, view.left.mean, view.right.mean, null);
  assert.ok(raw.hi - raw.lo >= 2.5);
  assert.ok(fit.hi - fit.lo < raw.hi - raw.lo);
  assert.ok(fit.hi - fit.lo <= 2);
  const leftNow = view.left.mean[view.left.mean.length - 1];
  const rightNow = view.right.mean[view.right.mean.length - 1];
  assert.ok(rightNow - leftNow > 0.5);
  assert.ok(leftNow > fit.lo && leftNow < fit.hi);
  assert.ok(rightNow > fit.lo && rightNow < fit.hi);
  assert.ok((rightNow - leftNow) / (fit.hi - fit.lo) > 0.25);
  // Every drawn sample has a full window, so the pulse is gone.
  for (const value of view.left.mean) assert.ok(Math.abs(value - 5.2) < 0.2);
  // The camera band widens the axis only when it is included.
  const withBand = liveMath.traceExtent(
    view.t, view.left.mean, view.right.mean, null,
    [view.left.lo, view.left.hi, view.right.lo, view.right.hi],
  );
  assert.ok(withBand.hi - withBand.lo > fit.hi - fit.lo);
  assert.ok(withBand.lo <= 4.5);
  assert.ok(withBand.hi >= 6.5);
});

test("BVI chart series stay on the raw samples", () => {
  const times = [0, 0.5, 1, 1.5, 2];
  const mean = [8, 8.4, 7.7, 8.1, 8.05];
  const view = liveMath.chartView("bvi", times, {
    left: { mean, lo: mean, hi: mean },
    right: { mean, lo: mean, hi: mean },
  }, 30);
  assert.deepEqual(view.t, times);
  assert.deepEqual(view.left.mean, mean);
  assert.deepEqual(view.right.mean, mean);
  const extent = liveMath.traceExtent(view.t, view.left.mean, view.right.mean, null);
  assert.equal(extent.lo, liveMath.yExtent(mean.concat(mean)).lo);
  assert.equal(extent.hi, liveMath.yExtent(mean.concat(mean)).hi);
});
