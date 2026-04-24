from agentic_switchboard.app import _static_dir


def test_ascii_avatar_lab_uses_media_keyframes_and_interpolation():
    html = (_static_dir() / "ascii-avatar-lab.html").read_text(encoding="utf-8")

    assert 'const KEYFRAME_IDS = Array.from({ length: 13 }' in html
    assert "const POSE_RANGES = {" in html
    assert "const TILE_WIDTH = 12;" in html
    assert "const TILE_HEIGHT = 8;" in html
    assert "const INDICATOR_STATES = ['paused', 'listening', 'thinking', 'speaking'];" in html
    assert "function findBestMotion(frameA, frameB, region = null) {" in html
    assert "function buildTileMotionField(frameA, frameB) {" in html
    assert "function sampleMotionField(field, row, col) {" in html
    assert 'data-indicator-card="speaking"' in html
    assert "function drawIndicatorFrame(state, ctx, nowSeconds, energy) {" in html
    assert "function renderIndicators(nowSeconds, energy) {" in html
    assert "function renderPlayheadFrame(playheadValue) {" in html
    assert "function activateMicrophone() {" in html
    assert "function beginDemoScript() {" in html
    assert "media/${id}.txt" in html
