"""Sentence-transformer embeddings with dirty-flag caching.

Uses multilingual MiniLM for Chinese-English mixed content.
Vectors are stored as JSON arrays in SQLite — sufficient for
personal-scale datasets (typically < 20,000 memos).
"""

from __future__ import annotations

import json
import sqlite3
import time

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from flomo_insight.utils.text import clean_memo_text


def compute_embeddings(
    conn: sqlite3.Connection,
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    force: bool = False,
    batch_size: int = 64,
) -> int:
    """Compute embeddings for all dirty memos. Returns count of memos processed."""
    from sentence_transformers import SentenceTransformer

    if force:
        conn.execute("UPDATE memos SET embedding_dirty = 1")
        conn.execute("DELETE FROM embeddings")
        conn.commit()

    # Get memos that need embedding
    rows = conn.execute(
        "SELECT slug, content FROM memos WHERE embedding_dirty = 1 ORDER BY rowid"
    ).fetchall()

    if not rows:
        return 0

    console = _get_console()
    console.print(f"[dim]Loading model {model_name}...[/dim]")
    model = SentenceTransformer(model_name)

    processed = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("({task.completed}/{task.total})"),
    ) as progress:
        task = progress.add_task("[cyan]Embedding memos...", total=len(rows))

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            texts = [clean_memo_text(r["content"]) for r in batch]
            vectors = model.encode(texts, show_progress_bar=False, batch_size=batch_size)

            for j, row in enumerate(batch):
                vector_json = json.dumps(vectors[j].tolist())
                conn.execute(
                    """INSERT OR REPLACE INTO embeddings (memo_slug, vector_json, model_name, generated_at)
                       VALUES (?, ?, ?, datetime('now'))""",
                    (row["slug"], vector_json, model_name),
                )
                conn.execute(
                    "UPDATE memos SET embedding_dirty = 0 WHERE slug = ?",
                    (row["slug"],),
                )
                processed += 1

            conn.commit()
            progress.update(task, completed=processed)

    return processed


def load_all_vectors(conn: sqlite3.Connection) -> tuple[list[str], "numpy.ndarray"]:
    """Load all embedding vectors as a numpy array. Returns (slugs, matrix)."""
    import numpy as np

    rows = conn.execute(
        "SELECT memo_slug, vector_json FROM embeddings ORDER BY memo_slug"
    ).fetchall()

    slugs: list[str] = []
    vectors: list[list[float]] = []
    for row in rows:
        slugs.append(row["memo_slug"])
        vectors.append(json.loads(row["vector_json"]))

    if not vectors:
        return [], np.array([])

    return slugs, np.array(vectors, dtype=np.float32)


def _get_console():
    from rich.console import Console
    return Console()
