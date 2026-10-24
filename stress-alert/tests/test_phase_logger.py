import asyncio
import csv
import itertools
import json

import pytest

from session.phase_logger import PhaseError, PhaseLogger


class FakeMarkers:
    available = True
    error = ""

    def __init__(self):
        self.pushed = []

    def push(self, text, t):
        self.pushed.append((text, t))


@pytest.fixture
def logger(tmp_path):
    ticks = itertools.count(100.0, 1.0)
    frames = []
    log = PhaseLogger(tmp_path, emit=frames.extend, markers=FakeMarkers(), now=lambda: next(ticks))
    log.frames = frames
    return log


def read_events(log):
    with (log.session.directory / "events.csv").open() as handle:
        return list(csv.DictReader(handle))


def test_session_creates_folder_meta_and_header(logger):
    session = logger.start_session("j b!", notes="first try")
    assert session.subject_id == "j-b"
    meta = json.loads((session.directory / "meta.json").read_text())
    assert meta["notes"] == "first try"
    assert meta["lsl_markers"] is True
    assert read_events(logger) == []
    assert logger.frames[-1]["type"] == "session" and logger.frames[-1]["active"]


def test_full_cycle_is_logged_emitted_and_marked(logger):
    logger.start_session("s1")
    for phase in ("baseline", "hold", "recovery", "baseline", "hold", "recovery", "end"):
        logger.mark(phase)
    rows = read_events(logger)
    assert [r["phase"] for r in rows][-1] == "end"
    assert len(rows) == 7
    assert all(r["source"] == "manual" for r in rows)
    phase_frames = [f for f in logger.frames if f["type"] == "phase"]
    assert [f["phase"] for f in phase_frames] == [r["phase"] for r in rows]
    assert logger.markers.pushed[0][0].startswith("baseline|")
    assert float(rows[0]["t"]) == logger.markers.pushed[0][1]


@pytest.mark.parametrize(
    "path,bad",
    [((), "hold"), (("baseline",), "recovery"), (("baseline", "hold"), "baseline")],
)
def test_out_of_order_phases_rejected(logger, path, bad):
    logger.start_session("s1")
    for phase in path:
        logger.mark(phase)
    with pytest.raises(PhaseError):
        logger.mark(bad)


def test_mark_without_session_and_double_start_rejected(logger):
    with pytest.raises(PhaseError):
        logger.mark("baseline")
    logger.start_session("s1")
    with pytest.raises(PhaseError):
        logger.start_session("s2")


def test_stop_session_writes_end_once(logger):
    logger.start_session("s1")
    logger.mark("baseline")
    directory = logger.session.directory
    logger.stop_session()
    logger.stop_session()  # no-op
    with (directory / "events.csv").open() as handle:
        phases = [r["phase"] for r in csv.DictReader(handle)]
    assert phases == ["baseline", "end"]
    assert logger.frames[-1] == {**logger.frames[-1], "active": False, "session_id": None}


async def test_timer_runs_protocol_then_ends(tmp_path):
    log = PhaseLogger(tmp_path)
    log.start_session("timed")
    log.start_timer({"baseline": 0.02, "hold": 0.01, "recovery": 0.02}, cycles=2)
    await asyncio.sleep(0.3)
    phases = [e["phase"] for e in log.session.events]
    assert phases == ["baseline", "hold", "recovery"] * 2 + ["end"]
    assert all(e["source"] == "timer" for e in log.session.events)
    assert log.timer_next is None


async def test_manual_mark_cancels_timer(tmp_path):
    log = PhaseLogger(tmp_path)
    log.start_session("override")
    log.start_timer({"baseline": 5, "hold": 5, "recovery": 5})
    await asyncio.sleep(0.01)
    assert log.timer_next == "hold"
    log.mark("end")
    await asyncio.sleep(0.01)
    assert log.timer_next is None
    assert [e["source"] for e in log.session.events] == ["timer", "manual"]
