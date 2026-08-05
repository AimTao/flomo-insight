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


# ── Near-duplicate detection ─────────────────────────────────────────────────

# Two cards are duplicates if one's normalized content is a substring of the
# other's, sharing at least MIN_DUP_OVERLAP characters. Short cards (poems,
# quotes) below this length are never swallowed by a longer card that happens
# to contain their text.
MIN_DUP_OVERLAP = 10

# Strip all punctuation + whitespace so "X。" / "X，" / 「X」 normalize to X.
_NON_PROSE_RE = re.compile(r"[^一-鿿㐀-䶿a-zA-Z0-9]+")


def _normalize_for_dup(text: str) -> str:
    """Collapse to prose characters only — punctuation/whitespace ignored."""
    return _NON_PROSE_RE.sub("", text)


def dedupe_cards(cards: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Drop near-duplicate cards, keeping the longest variant of each group.

    Args:
        cards: list of (slug, content, date) — content already cleaned.

    Returns:
        A list with duplicates removed. Within a group of subsuming cards
        (one content contained in another), only the longest is kept — the
        variant with the most prose survives, which is the more valuable card.

    Two cards count as duplicates when either's normalized text is a substring
    of the other's and the shorter one is at least MIN_DUP_OVERLAP chars.
    """
    kept: list[tuple[str, str, str]] = []
    for card in cards:
        nc = _normalize_for_dup(card[1])
        if not nc:
            continue
        dup = False
        for i, (_, kc, _) in enumerate(kept):
            nkc = _normalize_for_dup(kc)
            # Identical normalized content is always a dup, regardless of length.
            if nc == nkc:
                if len(nc) > len(nkc):
                    kept[i] = card
                dup = True
                break
            # Substring containment only counts when the shorter card is
            # substantial enough not to be a fragment swallowed by a longer text.
            if min(len(nc), len(nkc)) < MIN_DUP_OVERLAP:
                continue
            if nc in nkc or nkc in nc:
                # Keep the longer of the two.
                if len(nc) > len(nkc):
                    kept[i] = card
                dup = True
                break
        if not dup:
            kept.append(card)
    return kept
