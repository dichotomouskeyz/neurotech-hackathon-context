const assert = require("node:assert/strict");
const test = require("node:test");

const liveMath = require("../dashboard/static/live_math.js");

test("protocol defaults sum to one minute and closed loop sends the flag", () => {
  const body = liveMath.protocolBody({});
  assert.deepEqual(body, {
    baseline: 15,
    hold: 20,
    recovery: 20,
    continue_s: 5,
    cycles: 1,
  });
  assert.equal(liveMath.loopTotalSeconds(body), 60);
  const empty = liveMath.protocolBody({ baseline: "", hold: "0", recovery: "nope" });
  assert.equal(empty.baseline, 15);
  assert.equal(empty.hold, 20);
  assert.equal(empty.recovery, 20);
  const loop = liveMath.protocolBody({ baseline: "15", hold: "20" }, {
    closedLoop: true,
    subjectId: "jb",
  });
  assert.equal(loop.closed_loop, true);
  assert.equal(loop.subject_id, "jb");
  assert.equal(liveMath.loopTotalSeconds(loop), 60);
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
