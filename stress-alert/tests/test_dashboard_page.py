"""The operator page and the pure helpers agree on the long session."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_page_defaults_are_a_long_work_bout_after_a_short_baseline():
    html = (ROOT / "dashboard/static/index.html").read_text()
    js = (ROOT / "dashboard/static/app.js").read_text()
    assert 'id="dur-baseline" value="20"' in html
    assert 'id="dur-hold" value="0"' in html
    assert 'id="dur-recovery" value="20"' in html
    assert 'id="dur-continue" value="1200"' in html
    assert 'id="work-until-end"' in html
    assert 'id="recovered-within" value="5"' in html
    assert 'min="1" max="25"' in html
    assert "BFI within baseline (%)" in html
    assert 'id="present-hint"' in html
    assert "Long session (20 min work)" in html
    assert "Hold at 0 skips" in html
    assert "Work (s)" in html
    assert 'id="gate-tau"' in html
    assert "Recovery τ" in html
    assert "Each camera versus its own baseline median" in html
    assert "baseline: 12" not in js
    assert "liveMath.protocolBody" in js
    assert "renderStressTile()" in js


def test_heatmap_defaults_to_viridis_without_a_circular_clip():
    html = (ROOT / "dashboard/static/index.html").read_text()
    preview = (ROOT / "dashboard/static/heatmap_preview.html").read_text()
    heat = (ROOT / "dashboard/static/heatmap.js").read_text()
    app = (ROOT / "dashboard/static/app.js").read_text()
    for page in (html, preview):
        assert '<option value="viridis" selected>Viridis</option>' in page
        assert 'value="turbo" selected' not in page
    assert 'const DEFAULT_COLORMAP = "viridis"' in heat
    assert "clipAnatomicalPath" not in heat
    assert "ctx.clip(" not in heat
    assert "ellipse(" not in heat
    assert "updateColorbarGradient(brainHeatmap.colormap)" in app
    assert 'this.setColormap("turbo")' not in heat
    assert 'this.setColormap("coolwarm")' in heat


def test_live_math_node():
    script = ROOT / "tests" / "test_live_math.test.js"
    subprocess.run(["node", "--test", str(script)], check=True, cwd=ROOT)


def test_cycle_charts_shows_one_panel_at_a_time():
    html = (ROOT / "dashboard/static/index.html").read_text()
    css = (ROOT / "dashboard/static/styles.css").read_text()
    js = (ROOT / "dashboard/static/app.js").read_text()
    assert 'id="cycle" aria-pressed="false"' in html
    for card in ("card-bfi", "card-heatmap", "card-bvi"):
        assert f'id="{card}"' in html
    assert 'body[data-cycle="bfi"] #card-heatmap' in css
    assert 'body[data-cycle="heatmap"] #card-bfi' in css
    assert 'body[data-cycle="bvi"] #card-heatmap' in css
    assert 'const CYCLE = ["bfi", "heatmap", "bvi"]' in js
    assert "const CYCLE_MS = 8000" in js
