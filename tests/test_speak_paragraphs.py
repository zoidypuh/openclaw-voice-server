from io import StringIO

import httpx
import pytest

from maras_switchboard.speak_paragraphs import DEFAULT_SPEAK_ENDPOINT, main, speak_paragraphs, split_paragraphs


def test_split_paragraphs_collapses_wrapped_lines_and_skips_empty_blocks():
    text = """
    First line
    still first paragraph


      Second paragraph.

    Third
      paragraph
    """

    assert split_paragraphs(text) == [
        "First line still first paragraph",
        "Second paragraph.",
        "Third paragraph",
    ]


def test_speak_paragraphs_posts_each_paragraph_with_optional_fields():
    seen_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(request.read().decode("utf-8"))
        return httpx.Response(200, json={"ok": True, "spoken_text": request.url.path})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = speak_paragraphs(
        ["One.", "Two."],
        endpoint_url="http://example.test/api/runtime/speak",
        timeout_seconds=9.5,
        preset_name="expressive",
        speaker_name="Speaker-B",
        client=client,
    )

    assert [result["ok"] for result in results] == [True, True]
    assert seen_payloads == [
        '{"text":"One.","timeout_seconds":9.5,"preset_name":"expressive","speaker_name":"Speaker-B"}',
        '{"text":"Two.","timeout_seconds":9.5,"preset_name":"expressive","speaker_name":"Speaker-B"}',
    ]


def test_main_reads_stdin_and_uses_default_endpoint(monkeypatch, capsys):
    captured = {}

    def fake_speak_paragraphs(paragraphs, *, endpoint_url, timeout_seconds, preset_name, speaker_name, client=None):
        captured["paragraphs"] = paragraphs
        captured["endpoint_url"] = endpoint_url
        captured["timeout_seconds"] = timeout_seconds
        captured["preset_name"] = preset_name
        captured["speaker_name"] = speaker_name
        return [
            {"ok": True, "spoken_text": paragraph, "audio_bytes": 12}
            for paragraph in paragraphs
        ]

    monkeypatch.setattr("maras_switchboard.speak_paragraphs.speak_paragraphs", fake_speak_paragraphs)
    monkeypatch.setattr("sys.stdin", StringIO("Alpha\n\nBeta\nline two\n"))

    assert main([]) == 0
    assert captured == {
        "paragraphs": ["Alpha", "Beta line two"],
        "endpoint_url": DEFAULT_SPEAK_ENDPOINT,
        "timeout_seconds": 15.0,
        "preset_name": None,
        "speaker_name": None,
    }
    output = capsys.readouterr().out
    assert "Sent 2 paragraph(s)" in output
    assert "[2/2]" in output


def test_main_exits_with_parser_error_when_no_text_is_provided(monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO("   "))

    with pytest.raises(SystemExit, match="2"):
        main([])
