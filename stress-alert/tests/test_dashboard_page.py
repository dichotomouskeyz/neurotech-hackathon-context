"""The operator page and the pure helpers agree on the long session."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_page_defaults_are_a_long_work_bout_after_a_short_baseline():
    html = (ROOT / "dashboard/static/index.html").read_text()
    js = (ROOT / "dashboard/static/app.js").read_text()
    css = (ROOT / "dashboard/static/styles.css").read_text()
    assert 'id="dur-baseline" value="20"' in html
    assert 'id="dur-hold" value="0"' in html
    assert 'id="dur-recovery" value="20"' in html
    assert 'id="dur-continue" value="1200"' in html
    assert 'id="work-until-end"' not in html
    assert "Until End" not in html
    assert "0 skips" not in html
    assert "work_until_end = false" in js
    assert "work-until-end" not in js
    assert 'id="recovered-within" value="5"' in html
    assert 'min="1" max="25"' in html
    assert "BFI within baseline (%)" in html
    assert 'id="present-hint"' in html
    assert 'class="info-tip"' in html
    assert "info-btn" in html
    assert "Hold (s)" in html
    assert "Long session (20 min work)" not in html
    assert 'id="loop-start"' not in html
    assert 'id="device-disconnect"' not in html
    assert 'id="scan-stop"' not in html
    assert 'id="protocol-stop"' not in html
    assert 'id="btn-heatmap-demo"' not in html
    assert 'id="heatmap-live-chip"' not in html
    assert ">Search<" in html
    assert ">Start scan<" in html
    assert "Start scan (laser on)" not in html
    assert "Start scan (laser on)" not in js
    assert ">Run timed<" in html
    assert "closedLoop: true" in js
    assert "Stop protocol" in js
    assert "Disconnect" in js
    assert "Work (s)" in html
    assert 'id="gate-tau"' not in html
    assert 'id="tile-gate"' not in html
    assert 'id="gate-chart"' not in html
    assert "Recovery gate" not in html
    assert "Recovery τ" not in html
    assert "Each camera versus its own baseline median" in html
    assert "baseline: 12" not in js
    assert "liveMath.protocolBody" in js
    assert "renderStressTile()" in js
    assert 'id="coach"' in html
    phase = html.split('id="tile-phase"', 1)[1].split("</article>", 1)[0]
    assert 'id="phase-task"' in phase
    assert "phase-task" in js
    assert 'body[data-view="present"] #coach { display: none; }' in css
    heatmap_rule = (
        'body[data-view="present"] #card-heatmap {\n'
        "  grid-column: 1;\n"
        "  grid-row: 2 / span 2;"
    )
    assert heatmap_rule in css
    assert 'body[data-view="present"] #card-bfi { grid-column: 2; grid-row: 2;' in css
    assert 'body[data-view="present"] #card-bvi { grid-column: 2; grid-row: 3;' in css


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
