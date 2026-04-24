from maras_switchboard.text import (
    extract_speaker_directive,
    extract_speech_directives,
    has_probable_voice_transcript,
    should_drop_voice_transcript,
    strip_markdown,
)


def test_should_drop_voice_transcript_keeps_short_real_speech():
    assert should_drop_voice_transcript("hello there", 0.9) is False
    assert should_drop_voice_transcript("okay assistant", 0.9) is True


def test_should_drop_voice_transcript_keeps_short_words():
    assert should_drop_voice_transcript("stop", 0.3) is False
    assert should_drop_voice_transcript("quick pause", 0.3) is False


def test_should_drop_voice_transcript_filters_known_noise_phrases():
    assert should_drop_voice_transcript("Vielen Dank", 0.2, min_duration=0.5) is True
    assert should_drop_voice_transcript("what time is it", 1.2) is False


def test_should_drop_voice_transcript_keeps_short_polite_german_phrases_on_real_turns():
    assert should_drop_voice_transcript("Vielen Dank", 1.2, min_duration=0.5) is False
    assert should_drop_voice_transcript("Danke", 0.9, min_duration=0.5) is False


def test_should_drop_voice_transcript_filters_long_polite_noise_turns():
    assert should_drop_voice_transcript("Vielen Dank", 6.1, min_duration=0.5) is True
    assert should_drop_voice_transcript("Vielen Dank. Danke.", 47.8, min_duration=0.5) is True


def test_strip_markdown_removes_all_literal_asterisks():
    assert strip_markdown("*hi* **there** 2*3") == "hi there 23"


def test_strip_markdown_flattens_numbered_list_markers_for_tts():
    assert strip_markdown("1. first 2. second 3. third") == "1 first 2 second 3 third"


def test_extract_speaker_directive_accepts_known_speakers():
    assert extract_speaker_directive("[Speaker-A] hello") == ("speaker-a", "hello", False)
    assert extract_speaker_directive("[Speaker-B] hello") == ("speaker-b", "hello", False)


def test_extract_speaker_directive_respects_allowed_speakers():
    assert extract_speaker_directive("[Referee] hello", allowed_speakers={"referee"}) == (
        "referee",
        "hello",
        False,
    )
    assert extract_speaker_directive("[Narrator] hello", allowed_speakers={"referee"}) == (
        None,
        "[Narrator] hello",
        False,
    )


def test_extract_speech_directives_supports_speaker_then_style():
    assert extract_speech_directives("[Speaker-B][voice:expressive] Hello there.") == (
        "speaker-b",
        "expressive",
        "Hello there.",
        False,
    )


def test_has_probable_voice_transcript_accepts_short_real_speech():
    assert has_probable_voice_transcript("no", 0.25) is True
    assert has_probable_voice_transcript("actually wait", 0.4) is True


def test_has_probable_voice_transcript_rejects_empty_and_fillers():
    assert has_probable_voice_transcript("", 0.3) is False
    assert has_probable_voice_transcript("hey", 0.3) is False
    assert has_probable_voice_transcript("Vielen Dank", 0.2, min_duration=0.5) is False



def test_should_drop_voice_transcript_rejects_impossibly_dense_sentence_from_short_audio():
    assert should_drop_voice_transcript(
        "I'm going to make a cake with the remaining cream.",
        0.8,
        min_duration=0.5,
    ) is True



def test_has_probable_voice_transcript_rejects_impossibly_dense_sentence_from_short_audio():
    assert has_probable_voice_transcript(
        "I'm going to make a cake with the remaining cream.",
        0.8,
        min_duration=0.5,
    ) is False
