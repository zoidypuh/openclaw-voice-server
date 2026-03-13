import unittest

from openclaw_voice_server.text import (
    should_cancel_voice_input,
    should_drop_stt_false_positive,
    split_send_phrase,
    strip_markdown,
)


class TextUtilsTest(unittest.TestCase):
    def test_split_send_phrase_detects_final_word(self) -> None:
        text, should_send = split_send_phrase("mach bitte das licht aus fertig", "fertig")
        self.assertTrue(should_send)
        self.assertEqual(text, "mach bitte das licht aus")

    def test_split_send_phrase_accepts_small_misspelling(self) -> None:
        text, should_send = split_send_phrase("frage an openclaw ferdig", "fertig")
        self.assertTrue(should_send)
        self.assertEqual(text, "frage an openclaw")

    def test_split_send_phrase_keeps_draft_without_trigger(self) -> None:
        text, should_send = split_send_phrase("ich denke noch laut", "fertig")
        self.assertFalse(should_send)
        self.assertEqual(text, "ich denke noch laut")

    def test_strip_markdown_removes_basic_formatting(self) -> None:
        self.assertEqual(
            strip_markdown("**Hallo** [Welt](https://example.com) `code`"),
            "Hallo Welt code",
        )

    def test_should_cancel_voice_input_matches_stop(self) -> None:
        self.assertTrue(should_cancel_voice_input("stop"))
        self.assertTrue(should_cancel_voice_input("stopp"))
        self.assertFalse(should_cancel_voice_input("stop bitte jetzt"))

    def test_should_drop_stt_false_positive_drops_known_noise(self) -> None:
        self.assertTrue(should_drop_stt_false_positive("Vielen Dank", 2.0, 3.5))
        self.assertFalse(should_drop_stt_false_positive("echte frage", 2.0, 3.5))


if __name__ == "__main__":
    unittest.main()
