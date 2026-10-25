const assert = require("node:assert/strict");
const test = require("node:test");

const liveMath = require("../dashboard/static/live_math.js");

test("long session defaults skip the hold and run 20 minutes of work", () => {
  const body = liveMath.protocolBody({});
  assert.deepEqual(body, {
    baseline: 20,
    hold: 0,
    recovery: 20,
    continue_s: 1200,
    cycles: 1,
  });
  // Hold 0 skips the breath-hold and the recovery window.
  assert.equal(liveMath.loopTotalSeconds(body), 1220);
  assert.equal(liveMath.loopButtonLabel(body), "Long session (20 min work)");
  assert.equal(
    liveMath.loopButtonLabel(body, { workUntilEnd: true }),
    "Long session (until End)",
  );
  const empty = liveMath.protocolBody({ baseline: "", hold: "0", recovery: "nope" });
  assert.equal(empty.baseline, 20);
  assert.equal(empty.hold, 0);
  assert.equal(empty.recovery, 20);
  const loop = liveMath.protocolBody({ baseline: "15", hold: "12", recovery: "20", continue_s: "30" }, {
    closedLoop: true,
    subjectId: "jb",
    workUntilEnd: true,
  });
  assert.equal(loop.closed_loop, true);
  assert.equal(loop.subject_id, "jb");
  assert.equal(loop.work_until_end, true);
  assert.equal(liveMath.loopTotalSeconds(loop), 77);
  assert.equal(liveMath.loopButtonLabel({ continue_s: 32, baseline: 8, hold: 8, recovery: 12 }), "Closed loop (~60s)");
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
  const breath = liveMath.gateState({ gate: "locked", gate_reason: "locked_bfi", task: "coach" });
  assert.equal(breath.text, "Locked, breath");
  assert.equal(breath.headline, "Locked");
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
