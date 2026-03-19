import wave
from pathlib import Path

from openclaw_voice_server.calibrate_commands import _expand_paths, _read_wav_pcm16, resolve_command_action


def test_resolve_command_action_detects_interrupt():
    assert resolve_command_action("hey stop", send_phrase="hey go") == "interrupt"


def test_resolve_command_action_detects_send_phrase():
    assert resolve_command_action("tell me the weather hey go", send_phrase="hey go") == "send"


def test_resolve_command_action_accepts_go_fallback():
    assert resolve_command_action("tell me the weather go", send_phrase="hey go") == "send"


def test_read_wav_pcm16_reads_expected_audio(tmp_path: Path):
    wav_path = tmp_path / "sample.wav"
    expected_audio = b"\x01\x00\x02\x00\x03\x00\x04\x00"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(expected_audio)

    assert _read_wav_pcm16(wav_path) == expected_audio


def test_expand_paths_includes_wavs_from_directory(tmp_path: Path):
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    ignored = tmp_path / "note.txt"
    first.write_bytes(b"")
    second.write_bytes(b"")
    ignored.write_text("x")

    assert _expand_paths([str(tmp_path)]) == [first, second]
