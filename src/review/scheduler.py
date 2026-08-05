"""Review card content — clean flomo memo HTML into a readable card.

The review worker rotates cards by served frequency (see worker/review-worker.js);
all this module does is turn a memo's HTML content into the plain-text
version that gets stored in D1: tags stripped, structure kept.

No scheduling, no grading, no due dates.
"""

from __future__ import annotations

import re
from html import unescape

# Block-level tags become a newline so <p>/<li>/<div> structure reads as lines.
_BLOCK_TAGS = (
    r"</?(p|div|li|ul|ol|blockquote|h[1-6])([^>]*)>"
)
_BR_TAG = r"<br\s*/?>"
_OTHER_TAGS = r"<[^>]+>"


def to_plain_text(html: str) -> str:
    """Convert flomo memo HTML to readable plain text (line per block).

    flomo memo content is HTML (e.g. <p>, <ul>/<li>, <span>, <div>). The
    review card must read as a plain-text note, not raw markup.

    Lines that consist only of #tags (e.g. "#情绪", "#古诗 #苏轼") are
    dropped — the tag itself is noise on a review card.
    """
    text = html or ""
    text = re.sub(_BLOCK_TAGS, "\n", text)
    text = re.sub(_BR_TAG, "\n", text)
    text = re.sub(_OTHER_TAGS, "", text)
    text = unescape(text)
    # Keep one line per block: trim, drop empties, collapse blank lines.
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    # Drop lines that are purely #tags — no prose.
    lines = [ln for ln in lines if not _is_tag_only_line(ln)]
    return "\n".join(lines)


def strip_known_tags(text: str, tags: list[str]) -> str:
    """Remove #tag markers for the memo's known tags from cleaned text.

    Tag markers can lead a line ("#微信读书 #商业 #金句获得财富...") with
    no space before the prose, so tag-line filtering alone can't catch
    them. Stripping by the actual memo tags is exact: "#金句" is removed
    but "金句" in prose is left alone.
    """
    if not tags:
        return text
    # Sort longest-first so "#金句" doesn't partially match "#金句收藏".
    pattern = "|".join(re.escape(t) for t in sorted(tags, key=len, reverse=True))
    # Remove "#tag" markers (including the '#', and trailing space).
    cleaned = re.sub(rf"#(?:{pattern})\s?", "", text)
    # Collapse any leftover runs of '#' left by adjacency (e.g. "##书评").
    cleaned = re.sub(r"#\s*", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _is_tag_only_line(line: str) -> bool:
    """True if the line is one or more #tags with nothing else (e.g. "#情绪 #效率")."""
    return bool(re.fullmatch(r"(#\S+[\s#]*)+", line.strip()))
