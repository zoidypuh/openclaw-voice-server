from __future__ import annotations

import re

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
_CANCEL_WORDS = {"stop", "stopp"}
_TRAILING_FILLERS = {"bitte", "danke", "jetzt", "okay", "ok", "mal", "kurz"}

_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?—](?:\s|$)")
_EARLY_BREAK_RE = re.compile(r"[,;:](?:\s|$)")


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


def normalize_voice_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def should_drop_stt_false_positive(text: str, duration: float, silence_threshold: float) -> bool:
    normalized = normalize_voice_text(text)
    if not normalized:
        return True

    words = normalized.split()
    if normalized in _COMMON_NOISE and (duration < silence_threshold or len(words) <= 4):
        return True
    return False


def should_cancel_voice_input(text: str) -> bool:
    normalized = normalize_voice_text(text)
    if not normalized:
        return False
    return normalized in _CANCEL_WORDS and len(normalized.split()) <= 3


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

    target = normalize_voice_text(send_phrase)
    if not normalized_words:
        return stripped, False

    last_word = normalized_words[-1]
    if last_word == target or _within_edit_distance_one(last_word, target):
        if len(raw_words) > 1:
            kept = " ".join(raw_words[:-1])
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

