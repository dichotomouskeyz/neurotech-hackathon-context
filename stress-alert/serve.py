"""Entry point that works from any working directory: ``.venv/bin/python serve.py [--replay [CSV]]``.

Same as ``uv run python -m dashboard``; used by launchers that cannot set a cwd.
"""

import runpy

runpy.run_module("dashboard", run_name="__main__")
