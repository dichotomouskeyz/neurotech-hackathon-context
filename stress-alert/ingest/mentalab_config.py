"""Lane 2 switch. Mentalab / Mentalink stays off unless a session opts in.

``replay_mentalab.py`` and ``start_live_ecg`` read ``STRESS_ALERT_MENTALAB``.
Accepted on values are ``1``, ``true``, ``yes``, and ``on``. The replay CLI
also accepts ``--enable`` for that one process. Live recording still needs
``allow_live=True`` and the separate explorepy environment.

CSV readers stay importable so the modules can be turned back on. This
switch does not start or stop the dashboard or Open-Motion.

For research.
"""

from __future__ import annotations

import os

MENTALAB_ENV = "STRESS_ALERT_MENTALAB"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def mentalab_enabled(explicit: bool | None = None) -> bool:
    """Return whether Lane 2 entrypoints should run.

    ``explicit`` wins over the environment. ``None`` reads ``STRESS_ALERT_MENTALAB``.
    Unset, empty, and any value other than 1/true/yes/on mean off.
    """
    if explicit is not None:
        return bool(explicit)
    return os.environ.get(MENTALAB_ENV, "").strip().lower() in _TRUTHY
