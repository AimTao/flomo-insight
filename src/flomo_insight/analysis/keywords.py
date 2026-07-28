"""Keyword extraction using jieba tokenization and TF-IDF."""

from __future__ import annotations

import json
import sqlite3

from flomo_insight.utils.text import tokenize_for_tfidf, clean_memo_text


def extract_keywords_per_cluster(conn: sqlite3.Connection, top_n: int = 10) -> None:
    """Extract top TF-IDF keywords for each cluster and store in clusters.keywords."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    clusters = conn.execute("SELECT id FROM clusters").fetchall()
    if not clusters:
        return

    # Get all memo text for TF-IDF fitting
    all_memos = conn.execute("SELECT slug, content FROM memos").fetchall()
    if not all_memos:
        return

    all_texts = [tokenize_for_tfidf(clean_memo_text(m["content"])) for m in all_memos]

    # Global TF-IDF
    vectorizer = TfidfVectorizer(max_features=500, token_pattern=r"\S+")
    try:
        tfidf_matrix = vectorizer.fit_transform(all_texts)
    except ValueError:
        # Empty vocabulary — no meaningful text
        return

    feature_names = vectorizer.get_feature_names_out()

    # Build a lookup: slug → TF-IDF vector row index
    slug_to_idx = {m["slug"]: i for i, m in enumerate(all_memos)}

    for cluster_row in clusters:
        cluster_id = cluster_row["id"]

        # Get memos in this cluster
        memo_rows = conn.execute(
            "SELECT memo_slug FROM cluster_memos WHERE cluster_id = ?",
            (cluster_id,),
        ).fetchall()

        if not memo_rows:
            continue

        indices = [slug_to_idx[m["memo_slug"]] for m in memo_rows if m["memo_slug"] in slug_to_idx]
        if not indices:
            continue

        import numpy as np
        cluster_tfidf = np.asarray(tfidf_matrix[indices].mean(axis=0)).flatten()
        top_indices = cluster_tfidf.argsort()[-top_n:][::-1]
        top_keywords = [str(feature_names[i]) for i in top_indices if cluster_tfidf[i] > 0]

        conn.execute(
            "UPDATE clusters SET keywords = ? WHERE id = ?",
            (json.dumps(top_keywords, ensure_ascii=False), cluster_id),
        )

    conn.commit()
