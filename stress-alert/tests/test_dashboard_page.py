"""The operator page and the pure helpers agree on the one-minute closed loop."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_page_defaults_sum_to_one_minute_and_name_the_method():
    html = (ROOT / "dashboard/static/index.html").read_text()
    js = (ROOT / "dashboard/static/app.js").read_text()
    assert 'id="dur-baseline" value="15"' in html
    assert 'id="dur-hold" value="20"' in html
    assert 'id="dur-recovery" value="20"' in html
    assert 'id="dur-continue" value="5"' in html
    assert "Each camera versus its own baseline median" in html
    assert "baseline: 12" not in js
    assert "liveMath.protocolBody" in js
    assert "renderStressTile()" in js


def test_live_math_node():
    script = ROOT / "tests" / "test_live_math.test.js"
    subprocess.run(["node", "--test", str(script)], check=True, cwd=ROOT)
