from openclaw_voice_server.text import (
    command_send_phrases,
    detect_voice_control_command,
    has_probable_voice_transcript,
    should_cancel_voice_input,
    should_drop_voice_transcript,
    split_send_phrase,
)


def test_should_cancel_voice_input_accepts_simple_stop_words():
    assert should_cancel_voice_input("stop") is True
    assert should_cancel_voice_input("stopp") is True


def test_should_cancel_voice_input_accepts_short_stop_phrases():
    assert should_cancel_voice_input("stop bitte") is True
    assert should_cancel_voice_input("hey stop") is True
    assert should_cancel_voice_input("bonnie stopp jetzt") is True


def test_detect_voice_control_command_accepts_pause_phrases():
    assert detect_voice_control_command("hey pause") == "pause"
    assert detect_voice_control_command("pause bitte") == "pause"
    assert detect_voice_control_command("bonnie pausieren jetzt") == "pause"


def test_detect_voice_control_command_respects_selected_language():
    assert detect_voice_control_command("hey stop", language="en") == "interrupt"
    assert detect_voice_control_command("hey stop", language="de") is None
    assert detect_voice_control_command("bonnie stopp jetzt", language="de") == "interrupt"
    assert detect_voice_control_command("bonnie stopp jetzt", language="en") is None


def test_command_send_phrases_follow_selected_language():
    assert command_send_phrases("en") == ("hey go", "go")
    assert command_send_phrases("en-US") == ("hey go", "go")
    assert command_send_phrases("de") == ("hey los", "los")
    assert command_send_phrases("fr") == ()


def test_should_cancel_voice_input_rejects_long_or_non_cancel_phrases():
    assert should_cancel_voice_input("can you stop talking now") is False
    assert should_cancel_voice_input("hello there") is False
    assert detect_voice_control_command("hello there") is None


def test_should_drop_voice_transcript_keeps_short_real_speech():
    assert should_drop_voice_transcript("hello there", 0.9) is False
    assert should_drop_voice_transcript("okay bonnie", 0.9) is True


def test_should_drop_voice_transcript_keeps_short_control_commands():
    assert should_drop_voice_transcript("stop", 0.3) is False
    assert should_drop_voice_transcript("hey pause", 0.3) is False


def test_should_drop_voice_transcript_filters_known_noise_phrases():
    assert should_drop_voice_transcript("Vielen Dank", 0.2, min_duration=0.5) is True
    assert should_drop_voice_transcript("what time is it", 1.2) is False


def test_split_send_phrase_trims_trailing_go():
    assert split_send_phrase("tell me the weather go", "go") == ("tell me the weather", True)
    assert split_send_phrase("go", "go") == ("", True)
    assert split_send_phrase("we should go now", "go") == ("we should go now", False)


def test_split_send_phrase_trims_trailing_multi_word_phrase():
    assert split_send_phrase("tell me the weather hey go", "hey go") == ("tell me the weather", True)
    assert split_send_phrase("hey go", "hey go") == ("", True)
    assert split_send_phrase("hey maybe go now", "hey go") == ("hey maybe go now", False)


def test_has_probable_voice_transcript_accepts_short_real_speech():
    assert has_probable_voice_transcript("no", 0.25) is True
    assert has_probable_voice_transcript("actually wait", 0.4) is True


def test_has_probable_voice_transcript_rejects_empty_and_fillers():
    assert has_probable_voice_transcript("", 0.3) is False
    assert has_probable_voice_transcript("hey", 0.3) is False
    assert has_probable_voice_transcript("Vielen Dank", 0.2, min_duration=0.5) is False
