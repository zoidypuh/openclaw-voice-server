from __future__ import annotations

import re

from .catalog import ELEVENLABS_PRESETS

_COMMON_NOISE = {
    "vielen dank",
    "danke",
    "danke schoen",
    "danke schön",
    "you tschuess",
    "you tschuss",
    "you tschüss",
    "tschuess",
    "tschuss",
    "tschüss",
    "untertitel im auftrag des zdf",
    "bis zum naechsten mal",
    "bis zum nächsten mal",
    "vielen dank für's zuschauen",
    "vielen dank fürs zuschauen",
    "ich habe nicht gesagt",
}

# Always-drop hallucinations — these are never real user input.
_ALWAYS_DROP = {
    "tschüss",
    "tschuss",
    "tschuess",
    "bis zum nächsten mal",
    "bis zum naechsten mal",
    "untertitel im auftrag des zdf",
    "vielen dank für's zuschauen",
    "vielen dank fürs zuschauen",
}
_POLITE_NOISE_WORDS = {"vielen", "dank", "danke", "schoen", "schön"}
_IMPOSSIBLE_TRANSCRIPT_MIN_WORDS = 7
_IMPOSSIBLE_TRANSCRIPT_MAX_WORDS_PER_SECOND = 6.0
_IMPOSSIBLE_TRANSCRIPT_MAX_CHARS_PER_SECOND = 24.0
_LEADING_FILLERS = {"hey", "ok", "okay", "bitte", "assistant", "agent"}

_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?—](?:\s|$)")
_EARLY_BREAK_RE = re.compile(r"[,;:](?:\s|$)")
_ORDERED_LIST_MARKER_RE = re.compile(r"(?:(?<=^)|(?<=\n)|(?<=\r)|(?<=\s))(?P<number>\d+)\.\s+")
_VOICE_STYLE_RE = re.compile(
    r"^\s*\[(?:voice\s*[:=]\s*)?(?P<style>" + "|".join(ELEVENLABS_PRESETS.keys()) + r")\]\s*",
    re.IGNORECASE,
)
_SPEAKER_DIRECTIVE_RE = re.compile(r"^\s*\[(?P<speaker>[A-Za-z][A-Za-z0-9_-]{0,31})\]\s*")
_DEFAULT_SPEAKER_DIRECTIVES = {"speaker-a", "speaker-b"}


def strip_markdown(text: str) -> str:
    if len(_ORDERED_LIST_MARKER_RE.findall(text)) >= 2:
        text = _ORDERED_LIST_MARKER_RE.sub(lambda match: f'{match.group("number")} ', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("*", "")
    text = re.sub(r"[\U0001F600-\U0001FAFF]", "", text)
    return text.strip()


def extract_voice_style_directive(text: str) -> tuple[str | None, str, bool]:
    match = _VOICE_STYLE_RE.match(text)
    if match:
        style = match.group("style").lower()
        return style, text[match.end() :], False

    stripped = text.lstrip()
    if stripped.startswith("[") and "]" not in stripped and len(stripped) < 48:
        return None, text, True
    return None, text, False


def extract_speaker_directive(
    text: str,
    *,
    allowed_speakers: set[str] | None = None,
) -> tuple[str | None, str, bool]:
    allowed = {str(item or "").strip().lower() for item in (allowed_speakers or set()) if str(item or "").strip()}
    allowed.update(_DEFAULT_SPEAKER_DIRECTIVES)

    match = _SPEAKER_DIRECTIVE_RE.match(text)
    if match:
        speaker = match.group("speaker").lower()
        if speaker in allowed:
            return speaker, text[match.end() :], False

    stripped = text.lstrip()
    if stripped.startswith("[") and "]" not in stripped and len(stripped) < 48:
        return None, text, True
    return None, text, False


def extract_speech_directives(
    text: str,
    *,
    allowed_speakers: set[str] | None = None,
) -> tuple[str | None, str | None, str, bool]:
    speaker_name: str | None = None
    preset_name: str | None = None
    remaining = text

    for _ in range(4):
        consumed = False

        if speaker_name is None:
            speaker_name, next_text, waiting = extract_speaker_directive(
                remaining,
                allowed_speakers=allowed_speakers,
            )
            if waiting:
                return speaker_name, preset_name, remaining, True
            if speaker_name is not None:
                remaining = next_text
                consumed = True
                continue

        if preset_name is None:
            preset_name, next_text, waiting = extract_voice_style_directive(remaining)
            if waiting:
                return speaker_name, preset_name, remaining, True
            if preset_name is not None:
                remaining = next_text
                consumed = True
                continue

        if not consumed:
            break

    return speaker_name, preset_name, remaining, False


def normalize_voice_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _trim_transcript_fillers(words: list[str]) -> list[str]:
    trimmed = list(words)
    while trimmed and trimmed[0] in _LEADING_FILLERS:
        trimmed.pop(0)
    return trimmed


def _is_polite_noise_transcript(words: list[str]) -> bool:
    return bool(words) and all(word in _POLITE_NOISE_WORDS for word in words)



def _looks_like_impossibly_dense_transcript(words: list[str], duration: float) -> bool:
    if duration <= 0 or len(words) < _IMPOSSIBLE_TRANSCRIPT_MIN_WORDS:
        return False
    word_rate = len(words) / duration
    if word_rate <= _IMPOSSIBLE_TRANSCRIPT_MAX_WORDS_PER_SECOND:
        return False
    char_rate = len("".join(words)) / duration
    return char_rate >= _IMPOSSIBLE_TRANSCRIPT_MAX_CHARS_PER_SECOND



def should_drop_stt_false_positive(text: str, duration: float, min_duration: float) -> bool:
    normalized = normalize_voice_text(text)
    if not normalized:
        return True

    words = _trim_transcript_fillers(normalized.split())
    if not words:
        return True
    if normalized in _COMMON_NOISE and (duration < min_duration or len(words) <= 4):
        return True
    if _looks_like_impossibly_dense_transcript(words, duration):
        return True
    return False


def should_drop_voice_transcript(
    text: str,
    duration: float,
    *,
    min_duration: float = 0.5,
    min_words: int = 1,
) -> bool:
    normalized = normalize_voice_text(text)
    if not normalized:
        return True

    # Hard hallucination blacklist — always drop, regardless of duration.
    if normalized in _ALWAYS_DROP:
        return True

    if normalized in _COMMON_NOISE and duration < min_duration:
        return True

    # Whisper commonly hallucinates polite stock phrases on long low-information
    # captures. Keep short real "Danke" turns, but drop suspiciously long turns
    # that resolve to nothing except these polite noise words.
    if duration >= 4.0 and _is_polite_noise_transcript(normalized.split()):
        return True

    words = _trim_transcript_fillers(normalized.split())
    if not words:
        return True

    if _looks_like_impossibly_dense_transcript(words, duration):
        return True
    return len(words) < max(1, min_words)


def has_probable_voice_transcript(
    text: str,
    duration: float,
    *,
    min_duration: float = 0.2,
) -> bool:
    normalized = normalize_voice_text(text)
    if not normalized:
        return False

    words = _trim_transcript_fillers(normalized.split())
    if not words:
        return False

    if should_drop_stt_false_positive(text, duration, min_duration):
        return False
    return True


def pop_sentence_chunk(buf: str) -> tuple[str | None, str]:
    match = _SENTENCE_BOUNDARY_RE.search(buf)
    if not match:
        return None, buf
    chunk = buf[: match.end()]
    remainder = buf[match.end() :]
    return (chunk if chunk.strip() else None), remainder


def pop_early_chunk(
    buf: str,
    min_chars: int = 14,
    min_words: int = 2,
    max_chars: int = 36,
) -> tuple[str | None, str]:
    text = buf.strip()
    if not text:
        return None, buf

    words = len(text.split())
    if len(text) < min_chars and words < min_words:
        return None, buf

    match = _EARLY_BREAK_RE.search(buf)
    if match:
        cutoff = match.end()
    else:
        cutoff = min(len(buf), max_chars)
        window = buf[:cutoff]
        space_index = window.rfind(" ")
        if space_index >= min_chars:
            cutoff = space_index
        elif words < min_words:
            return None, buf

    chunk = buf[:cutoff]
    remainder = buf[cutoff:]
    return (chunk if chunk.strip() else None), remainder
