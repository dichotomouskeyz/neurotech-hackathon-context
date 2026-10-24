"""The one shared clock for every ``t`` in the message contract.

LSL's ``local_clock()`` is used because ECG and Open-Motion samples arrive through LSL
with timestamps on that clock. On macOS it is offset from ``time.monotonic()`` by
millions of seconds, so the two must never be mixed.
"""

import time

try:
    from pylsl import local_clock as now

    NAME = "lsl_local_clock"
except Exception:  # pragma: no cover - liblsl missing on this host
    now = time.monotonic
    NAME = "monotonic"

__all__ = ["NAME", "now"]
