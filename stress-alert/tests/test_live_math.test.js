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

test("BFI bounds keep the raw pulse and follow a slow level shift", () => {
  const hz = 40;
  const times = [];
  const left = [];
  const right = [];
  for (let i = 0; i < hz * 24; i += 1) {
    const time = i / hz;
    times.push(time);
    const center = time < 14 ? 6 : 7;
    const pulse = Math.sin(2 * Math.PI * 1.1 * time);
    left.push(center + pulse);
    right.push(center + 0.4 + 0.9 * pulse);
  }
  const earlyN = hz * 12;
  const early = liveMath.bfiBounds(
    times.slice(0, earlyN),
    [left.slice(0, earlyN), right.slice(0, earlyN)],
    null,
  );
  // Pulse lives near 5 to 7.4. Bounds hold that, with headroom, and stay
  // inside a wider stuck span such as 4.5 to 8.
  assert.ok(early.lo < 5.15 && early.lo > 4.2, `early lo ${early.lo}`);
  assert.ok(early.hi > 7.2 && early.hi < 8.2, `early hi ${early.hi}`);
  const recent = [];
  for (let i = 0; i < earlyN; i += 1) recent.push(left[i], right[i]);
  assert.ok(Math.min(...recent) >= early.lo);
  assert.ok(Math.max(...recent) <= early.hi);

  const shifted = liveMath.bfiBounds(times, [left, right], null);
  // The last 8 s are the 6 to 8 band. The old 5 to 7 stretch has left the window.
  assert.ok(shifted.lo > 5.4, `shifted lo ${shifted.lo}`);
  assert.ok(shifted.hi > 7.9 && shifted.hi < 9, `shifted hi ${shifted.hi}`);
  assert.ok(shifted.hi - shifted.lo < 3.2);
  const tail = [];
  for (let i = 0; i < times.length; i += 1) {
    if (times[i] >= times[times.length - 1] - liveMath.BFI_BOUND_WINDOW_S) {
      tail.push(left[i], right[i]);
    }
  }
  assert.ok(Math.min(...tail) >= shifted.lo);
  assert.ok(Math.max(...tail) <= shifted.hi);

  const spiked = left.slice();
  spiked[spiked.length - 10] = 40;
  const withSpike = liveMath.bfiBounds(times, [spiked, right], null);
  assert.ok(withSpike.hi < 12, `spike hi ${withSpike.hi}`);

  const band = liveMath.bfiBounds(times, [left, right, left.map((v) => v - 1.5), right.map((v) => v + 1.5)], null);
  assert.ok(band.hi - band.lo > shifted.hi - shifted.lo);
});

test("BVI scale still snaps to the half-unit grid", () => {
  const extent = liveMath.yExtent([8, 8.05, 8.02, 8.1, 7.98, 8.04, 8.01, 8.03]);
  assert.equal(extent.lo * 2, Math.round(extent.lo * 2));
  assert.equal(extent.hi * 2, Math.round(extent.hi * 2));
  assert.ok(extent.hi - extent.lo >= 0.5);
  assert.ok(extent.hi - extent.lo <= 1.5);
});
