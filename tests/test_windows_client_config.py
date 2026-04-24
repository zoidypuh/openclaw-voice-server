import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_client_uses_maras_switchboard_window_title():
    config = json.loads((ROOT / "clients/windows/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    lib_rs = (ROOT / "clients/windows/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    setup_html = (ROOT / "src/maras_switchboard/static/setup.html").read_text(encoding="utf-8")

    assert config["productName"] == "Mara's Switchboard"
    assert """.title("Mara's Switchboard")""" in lib_rs
    assert "<title>Mara's Switchboard</title>" in setup_html


def test_windows_client_start_voice_reads_pause_label_not_active_class():
    lib_rs = (ROOT / "clients/windows/src-tauri/src/lib.rs").read_text(encoding="utf-8")

    assert "const label = button.textContent.trim().toLowerCase();" in lib_rs
    assert "document.body.dataset.state === 'paused' || label === 'paused'" in lib_rs
    assert "button.classList.contains('active')" not in lib_rs
