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
    "untertitel im auftrag des zdf",
    "bis zum naechsten mal",
    "bis zum nächsten mal",
}
_COMMAND_KEYWORDS = {
    "de": {
        "interrupt": {"stopp"},
        "pause": {"pause", "pausieren"},
        "send_phrases": ("hey los", "los"),
    },
    "en": {
        "interrupt": {"stop"},
        "pause": {"pause"},
        "send_phrases": ("hey go", "go"),
    },
}
_TRAILING_FILLERS = {"bitte", "danke", "jetzt", "okay", "ok", "mal", "kurz"}
_LEADING_FILLERS = {"hey", "ok", "okay", "bitte", "bonnie", "clyde"}

_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?—](?:\s|$)")
_EARLY_BREAK_RE = re.compile(r"[,;:](?:\s|$)")
_VOICE_STYLE_RE = re.compile(
    r"^\s*\[(?:voice\s*[:=]\s*)?(?P<style>" + "|".join(ELEVENLABS_PRESETS.keys()) + r")\]\s*",
    re.IGNORECASE,
)


def strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
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


def normalize_voice_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def resolve_command_language(language: str | None) -> str | None:
    normalized = str(language or "").strip().lower()
    if not normalized:
        return None
    for prefix in _COMMAND_KEYWORDS:
        if normalized == prefix or normalized.startswith(f"{prefix}-"):
            return prefix
    return None


def command_send_phrases(language: str | None) -> tuple[str, ...]:
    resolved = resolve_command_language(language)
    if resolved is None:
        return ()
    return tuple(_COMMAND_KEYWORDS[resolved]["send_phrases"])


def _trim_control_fillers(words: list[str]) -> list[str]:
    trimmed = list(words)
    while trimmed and trimmed[0] in _LEADING_FILLERS:
        trimmed.pop(0)
    while trimmed and trimmed[-1] in _TRAILING_FILLERS:
        trimmed.pop()
    return trimmed


def should_drop_stt_false_positive(text: str, duration: float, min_duration: float) -> bool:
    normalized = normalize_voice_text(text)
    if not normalized:
        return True

    words = _trim_control_fillers(normalized.split())
    if not words:
        return True
    if normalized in _COMMON_NOISE and (duration < min_duration or len(words) <= 4):
        return True
    return False


def should_drop_voice_transcript(
    text: str,
    duration: float,
    *,
    min_duration: float = 0.5,
    min_words: int = 1,
    command_language: str | None = None,
) -> bool:
    if detect_voice_control_command(text, language=command_language):
        return False

    if should_drop_stt_false_positive(text, duration, min_duration):
        return True

    normalized = normalize_voice_text(text)
    words = _trim_control_fillers(normalized.split())
    if not words:
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

    words = _trim_control_fillers(normalized.split())
    if not words:
        return False

    if should_drop_stt_false_positive(text, duration, min_duration):
        return False
    return True


def detect_voice_control_command(text: str, *, language: str | None = None) -> str | None:
    normalized = normalize_voice_text(text)
    if not normalized:
        return None
    words = _trim_control_fillers(normalized.split())
    if not words or len(words) > 3:
        return None
    resolved = resolve_command_language(language)
    if resolved is None:
        pause_words = set().union(*(keywords["pause"] for keywords in _COMMAND_KEYWORDS.values()))
        interrupt_words = set().union(*(keywords["interrupt"] for keywords in _COMMAND_KEYWORDS.values()))
    else:
        pause_words = _COMMAND_KEYWORDS[resolved]["pause"]
        interrupt_words = _COMMAND_KEYWORDS[resolved]["interrupt"]
    if any(word in pause_words for word in words):
        return "pause"
    if any(word in interrupt_words for word in words):
        return "interrupt"
    return None


def should_cancel_voice_input(text: str, *, language: str | None = None) -> bool:
    return detect_voice_control_command(text, language=language) == "interrupt"


def _within_edit_distance_one(source: str, target: str) -> bool:
    if source == target:
        return True
    if abs(len(source) - len(target)) > 1:
        return False

    i = 0
    j = 0
    edits = 0
    while i < len(source) and j < len(target):
        if source[i] == target[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if len(source) > len(target):
            i += 1
        elif len(source) < len(target):
            j += 1
        else:
            i += 1
            j += 1

    if i < len(source) or j < len(target):
        edits += 1
    return edits <= 1


def split_send_phrase(text: str, send_phrase: str) -> tuple[str, bool]:
    stripped = text.strip()
    normalized = normalize_voice_text(stripped)
    if not normalized:
        return stripped, False

    raw_words = stripped.split()
    normalized_words = normalized.split()
    while len(normalized_words) > 1 and normalized_words[-1] in _TRAILING_FILLERS:
        normalized_words.pop()
        raw_words.pop()

    target_words = normalize_voice_text(send_phrase).split()
    if not normalized_words or not target_words or len(normalized_words) < len(target_words):
        return stripped, False

    suffix_words = normalized_words[-len(target_words) :]
    prefix_words = suffix_words[:-1]
    target_prefix = target_words[:-1]
    suffix_last = suffix_words[-1]
    target_last = target_words[-1]

    if prefix_words == target_prefix and (suffix_last == target_last or _within_edit_distance_one(suffix_last, target_last)):
        kept_words = raw_words[:-len(target_words)]
        if kept_words:
            kept = " ".join(kept_words)
            return kept.rstrip(" \t\r\n,.;:!?-"), True
        return "", True
    return stripped, False


def pop_sentence_chunk(buf: str) -> tuple[str | None, str]:
    match = _SENTENCE_BOUNDARY_RE.search(buf)
    if not match:
        return None, buf
    chunk = buf[: match.end()]
    remainder = buf[match.end() :]
    return (chunk if chunk.strip() else None), remainder


def pop_early_chunk(
    buf: str,
    min_chars: int = 24,
    min_words: int = 3,
    max_chars: int = 48,
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
