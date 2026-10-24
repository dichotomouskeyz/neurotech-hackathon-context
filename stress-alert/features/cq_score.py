"""Map per-camera quality or contact-quality inputs to one score from 0 to 1.

Two input styles are accepted, because the SDK exposes both:

- Corrected-scan CSV labels such as ``ok``, ``ts_corrected``, ``nan_filled``,
  and ``wide_interval`` (the sample file in openmotion-bloodflow-app).
  Pipeline rank, worst last, is ``ok < ts_corrected < nan_filled < wide_interval``.
- Contact-quality records from ``MotionInterface.contact_quality_workflow.check``.
  See OpenwaterHealth/openmotion-sdk ``scripts/sdk_examples.py``. A camera
  passes when ``dark_max_dn`` is at or below the dark threshold and
  ``light_avg_dn`` is at or above the light threshold. The defaults here
  match that example: dark 3.0 DN, light 15.0 DN.

``bad_coupling`` is true when the mean score is strictly below ``bad_below``
(default 0.5). Use it as a gate: do not trust pulse or later stress features
on that window. It is not a clinical contact assessment.

For research.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

# Usable sample = 1. A filled-in or biased sample scores lower. A dropout
# scores 0. wide_interval still emits numbers, but those numbers sit on a
# stretched dark baseline, so they count as poor rather than missing.
LABEL_SCORE = {
    "ok": 1.0,
    "pass": 1.0,
    "passed": 1.0,
    "ts_corrected": 0.85,
    "wide_interval": 0.35,
    "nan_filled": 0.0,
    "fail": 0.0,
    "failed": 0.0,
    "bad": 0.0,
}

DEFAULT_BAD_BELOW = 0.5
DEFAULT_DARK_MAX_DN = 3.0
DEFAULT_LIGHT_MIN_DN = 15.0


@dataclass(frozen=True)
class CqResult:
    """Mean per-camera score and the coupling gate derived from it."""

    score: float
    bad_coupling: bool
    n: int


def cq_score(
    values: Sequence[object],
    *,
    bad_below: float = DEFAULT_BAD_BELOW,
    dark_max_dn: float = DEFAULT_DARK_MAX_DN,
    light_min_dn: float = DEFAULT_LIGHT_MIN_DN,
) -> CqResult:
    """Score one frame or one contact check.

    ``values`` is one entry per camera. Entries may be quality labels,
    booleans (passed / failed), numbers already on 0 to 1, or mappings with
    ``passed``, ``quality``, ``score``, or ``light_avg_dn`` and ``dark_max_dn``.
    Blank entries are skipped. An unknown label raises ``ValueError``.
    """
    if not values:
        raise ValueError("cq_score needs at least one per-camera value")
    if not 0.0 <= bad_below <= 1.0:
        raise ValueError("bad_below must be between 0 and 1")
    scores = [
        _camera_score(value, dark_max_dn=dark_max_dn, light_min_dn=light_min_dn)
        for value in values
    ]
    usable = [score for score in scores if score is not None]
    if not usable:
        raise ValueError("cq_score found no usable per-camera values")
    score = float(sum(usable) / len(usable))
    score = min(1.0, max(0.0, score))
    return CqResult(score=score, bad_coupling=score < bad_below, n=len(usable))


def _camera_score(
    value: object,
    *,
    dark_max_dn: float,
    light_min_dn: float,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        key = value.strip().lower()
        if not key or key == "nan":
            return None
        if key not in LABEL_SCORE:
            raise ValueError(f"unknown quality label: {value!r}")
        return LABEL_SCORE[key]
    if isinstance(value, Mapping):
        return _mapping_score(value, dark_max_dn=dark_max_dn, light_min_dn=light_min_dn)
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number):
            return None
        return _unit_interval(number)
    raise TypeError(f"unsupported quality value: {value!r}")


def _mapping_score(
    record: Mapping[str, object],
    *,
    dark_max_dn: float,
    light_min_dn: float,
) -> float | None:
    if "light_avg_dn" in record or "dark_max_dn" in record:
        return _graded_contact(record, dark_max_dn=dark_max_dn, light_min_dn=light_min_dn)
    if "passed" in record:
        return 1.0 if bool(record["passed"]) else 0.0
    if "quality" in record:
        return _camera_score(
            record["quality"], dark_max_dn=dark_max_dn, light_min_dn=light_min_dn
        )
    if "score" in record:
        return _camera_score(
            record["score"], dark_max_dn=dark_max_dn, light_min_dn=light_min_dn
        )
    raise ValueError(
        "contact record needs passed, quality, score, or light_avg_dn and dark_max_dn"
    )


def _graded_contact(
    record: Mapping[str, object],
    *,
    dark_max_dn: float,
    light_min_dn: float,
) -> float:
    """1 when the SDK pass rule holds, otherwise the closer term, capped at 1.

    A camera at or inside both thresholds scores 1. A miss falls toward 0 as
    light drops below the floor or dark rises above the ceiling. Dark equal to
    twice the threshold, or light equal to 0, scores 0.
    """
    light = record.get("light_avg_dn")
    dark = record.get("dark_max_dn")
    if light is None or dark is None:
        if "passed" in record:
            return 1.0 if bool(record["passed"]) else 0.0
        raise ValueError("contact DN record needs light_avg_dn and dark_max_dn")
    if light_min_dn <= 0 or dark_max_dn <= 0:
        raise ValueError("DN thresholds must be positive")
    light_f = float(light)
    dark_f = float(dark)
    if math.isnan(light_f) or math.isnan(dark_f):
        raise ValueError("contact DN values must be finite")
    if dark_f <= dark_max_dn:
        dark_term = 1.0
    else:
        dark_term = max(0.0, 1.0 - (dark_f - dark_max_dn) / dark_max_dn)
    if light_f >= light_min_dn:
        light_term = 1.0
    else:
        light_term = max(0.0, light_f / light_min_dn)
    return min(light_term, dark_term)


def _unit_interval(number: float) -> float:
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise ValueError(f"numeric quality must be between 0 and 1, got {number}")
    return float(number)
