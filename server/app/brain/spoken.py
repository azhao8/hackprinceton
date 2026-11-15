"""Clean a line before Miguel says it out loud (issue #81): no emojis, no markdown.

The prompt says "no emojis" and "plain spoken sentences", but models slip (qwen3.8 once ended a
line with a water-drop emoji). A text-to-speech voice reads "**" or "💧" aloud or chokes on it,
so every `say` goes through `clean_spoken` first, whichever LLM wrote it.
"""

from __future__ import annotations

import re

# Emoji and pictographs, dingbats, flags, keycaps, variation selectors and joiners.
_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # mahjong .. symbols and pictographs extended-A (faces, objects, flags)
    "\U00002600-\U000027BF"   # misc symbols, dingbats
    "\U00002B00-\U00002BFF"   # arrows and stars used as emoji
    "\U0001F1E6-\U0001F1FF"   # regional indicators (flags)
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U0000200D"              # zero-width joiner
    "\U000020E3"              # combining keycap
    "\U000E0020-\U000E007F"   # tag characters (subdivision flags)
    "]+"
)
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")            # [text](url) -> text; ![alt](img) -> alt
_CODE = re.compile(r"`+([^`]*)`+")                         # `code` -> code
_EMPHASIS = re.compile(r"(\*{1,3}|_{2,3})(\S(?:.*?\S)?)\1")  # **bold**, *italic*, __bold__ -> the words
_LINE_START = re.compile(r"^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+•]\s+|\d{1,2}[.)]\s+)", re.MULTILINE)  # headings, quotes, bullets
_LEFTOVER = re.compile(r"[*_#`~|]+")                       # stray markdown characters


def clean_spoken(text: str) -> str:
    """`text` without emojis or markdown, with tidy spaces. May return "" (it was all emoji)."""
    t = _EMOJI.sub(" ", text)
    t = _LINK.sub(r"\1", t)
    t = _CODE.sub(r"\1", t)
    t = _EMPHASIS.sub(r"\2", t)
    t = _LINE_START.sub("", t)
    t = _LEFTOVER.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s+([.,!?;:])", r"\1", t)   # "Mom ." (an emoji was before the dot) -> "Mom."
