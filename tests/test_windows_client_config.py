import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_client_uses_maras_switchboard_window_title():
    config = json.loads((ROOT / "clients/windows/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    lib_rs = (ROOT / "clients/windows/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    setup_html = (ROOT / "src/maras_switchboard/static/setup.html").read_text(encoding="utf-8")

    assert config["productName"] == "Mara's Switchboard"
    assert """const APP_WINDOW_TITLE: &str = "Mara's Switchboard";""" in lib_rs
    assert "OpenClaw Voice" not in lib_rs
    assert """.title(APP_WINDOW_TITLE)""" in lib_rs
    assert "window.set_title(APP_WINDOW_TITLE)" in lib_rs
    assert 'format!("{APP_WINDOW_TITLE}: {}", state.label())' in lib_rs
    assert "<title>Mara's Switchboard</title>" in setup_html


def test_windows_client_start_voice_reads_pause_label_not_active_class():
    lib_rs = (ROOT / "clients/windows/src-tauri/src/lib.rs").read_text(encoding="utf-8")

    assert "const label = button.textContent.trim().toLowerCase();" in lib_rs
    assert "document.body.dataset.state === 'paused' || label === 'paused'" in lib_rs
    assert "button.classList.contains('active')" not in lib_rs


def test_windows_client_interrupt_menu_uses_hidden_manual_interrupt_hook():
    lib_rs = (ROOT / "clients/windows/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    voice_html = (ROOT / "src/maras_switchboard/static/voice.html").read_text(encoding="utf-8")

    assert 'MENU_INTERRUPT => invoke_voice_action(app, "__marasSwitchboardManualInterrupt")' in lib_rs
    assert "window.__marasSwitchboardManualInterrupt = manualInterrupt;" in voice_html
    assert 'id="interrupt-btn" class="mini-btn hidden"' in voice_html


def test_windows_client_shortcuts_separate_hold_and_toggle_talk():
    lib_rs = (ROOT / "clients/windows/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    voice_html = (ROOT / "src/maras_switchboard/static/voice.html").read_text(encoding="utf-8")

    assert 'const HOLD_TO_TALK_SHORTCUT: &str = "Alt+Shift+A";' in lib_rs
    assert 'const TOGGLE_TMUX_TALK_SHORTCUT: &str = "Alt+Shift+W";' in lib_rs
    assert "with_shortcuts(vec![hold_to_talk_shortcut, toggle_tmux_talk_shortcut])" in lib_rs
    assert 'ShortcutState::Pressed => {\n                        invoke_voice_action(app, "__marasSwitchboardTmuxHoldToTalkStart");\n                    }\n                    ShortcutState::Released => {\n                        invoke_voice_action(app, "__marasSwitchboardTmuxHoldToTalkEnd");\n                    }' in lib_rs
    assert 'ShortcutState::Pressed => {\n                        invoke_voice_action(app, "__marasSwitchboardTmuxHoldToTalkToggle");\n                    }\n                    ShortcutState::Released => {}' in lib_rs
    assert "window.__marasSwitchboardTmuxHoldToTalkStart = () => beginHoldToTalk({ tmuxOnly: true });" in voice_html
    assert "window.__marasSwitchboardTmuxHoldToTalkEnd = () => endHoldToTalk();" in voice_html
    assert "window.__marasSwitchboardTmuxHoldToTalkToggle = () => toggleHoldToTalk({ tmuxOnly: true });" in voice_html


def test_windows_client_tray_has_talking_state_for_ptt_recording():
    lib_rs = (ROOT / "clients/windows/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    voice_html = (ROOT / "src/maras_switchboard/static/voice.html").read_text(encoding="utf-8")
    state_py = (ROOT / "src/maras_switchboard/windows_client_state.py").read_text(encoding="utf-8")

    assert '"talking" => Self::Talking,' in lib_rs
    assert 'Self::Listening => "idle - not recording",' in lib_rs
    assert 'Self::Talking => "RECORDING - PTT active",' in lib_rs
    assert "let neutral = [126, 132, 142, 255];" in lib_rs
    assert "let red = [238, 43, 53, 255];" in lib_rs
    assert "TrayState::Talking => {" in lib_rs
    assert "draw_mic_glyph(&mut rgba, white);" in lib_rs
    assert "draw_filled_circle(&mut rgba, 23, 9, 5, red);" in lib_rs
    assert '"talking",' in state_py
    assert "if (isHoldToTalkActive()) {\n    return 'talking';\n  }" in voice_html
    assert "syncShellState({ force: true });\n}" in voice_html
