"""Text utilities — Chinese tokenization (jieba) and cleaning."""

from __future__ import annotations

import re

import jieba


def clean_memo_text(content: str) -> str:
    """Strip markdown formatting and URLs from memo content for analysis."""
    # Remove URLs
    text = re.sub(r"https?://\S+", "", content)
    # Remove markdown links [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove markdown headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove markdown bold/italic
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    # Remove code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove quotes
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    """Tokenize text using jieba, returning meaningful tokens only."""
    cleaned = clean_memo_text(text)
    words = jieba.cut(cleaned)
    # Filter: keep words >= 2 chars, skip pure punctuation/digits
    return [
        w.strip()
        for w in words
        if len(w.strip()) >= 2 and not re.match(r"^[\d\W_]+$", w.strip())
    ]


def tokenize_for_tfidf(text: str) -> str:
    """Tokenize and join with spaces for TfidfVectorizer input."""
    return " ".join(tokenize(text))
