"""Tag co-occurrence analysis — builds a weighted adjacency graph of tag pairs."""

from __future__ import annotations

import sqlite3


def compute_cooccurrence(conn: sqlite3.Connection) -> int:
    """Compute tag co-occurrence edges from memo_tags. Returns edge count."""
    conn.execute("DELETE FROM tag_cooccurrence")
    conn.commit()

    # Get all (memo_slug, tag_id) pairs
    rows = conn.execute(
        "SELECT memo_slug, tag_id FROM memo_tags ORDER BY memo_slug"
    ).fetchall()

    if not rows:
        return 0

    # Group by memo
    memo_tags: dict[str, list[int]] = {}
    for row in rows:
        slug = row["memo_slug"]
        if slug not in memo_tags:
            memo_tags[slug] = []
        memo_tags[slug].append(row["tag_id"])

    # Count co-occurrences
    edges: dict[tuple[int, int], int] = {}
    for tag_ids in memo_tags.values():
        if len(tag_ids) < 2:
            continue
        for i in range(len(tag_ids)):
            for j in range(i + 1, len(tag_ids)):
                a, b = tag_ids[i], tag_ids[j]
                if a > b:
                    a, b = b, a  # canonical ordering
                key = (a, b)
                edges[key] = edges.get(key, 0) + 1

    # Store edges
    for (a, b), weight in edges.items():
        conn.execute(
            """INSERT OR REPLACE INTO tag_cooccurrence (tag_a_id, tag_b_id, weight)
               VALUES (?, ?, ?)""",
            (a, b, weight),
        )

    conn.commit()
    return len(edges)
