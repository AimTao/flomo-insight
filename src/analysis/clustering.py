"""UMAP dimensionality reduction + HDBSCAN clustering.

Clusters memos into topic groups and stores assignments in the
clusters and cluster_memos tables.
"""

from __future__ import annotations

import sqlite3

from src.analysis.embeddings import load_all_vectors


def cluster_memos(
    conn: sqlite3.Connection,
    min_cluster_size: int = 5,
) -> int:
    """Run UMAP + HDBSCAN clustering on all embedded memos.

    Returns the number of clusters found (excluding noise).
    """
    import numpy as np
    import umap
    import hdbscan

    slugs, vectors = load_all_vectors(conn)
    if len(vectors) == 0:
        return 0

    console = _get_console()
    console.print(f"[dim]Clustering {len(vectors)} memos...[/dim]")

    n_samples = len(vectors)

    # UMAP: reduce to 15 dims (or fewer if we have few samples)
    n_components = min(15, n_samples - 1, max(n_samples // 10, 2))
    n_neighbors = min(15, n_samples - 1)
    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=0.1,
        metric="cosine",
        random_state=42,
    )
    reduced = reducer.fit_transform(vectors)

    # HDBSCAN
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min(min_cluster_size, n_samples - 1),
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(reduced)

    # Store results
    # Clear previous cluster data
    conn.execute("DELETE FROM cluster_memos")
    conn.execute("DELETE FROM topic_trends")
    conn.execute("DELETE FROM tag_cooccurrence")
    conn.execute("DELETE FROM clusters")

    unique_labels = set(labels)
    cluster_count = 0

    for label in unique_labels:
        if label == -1:
            continue  # noise
        mask = labels == label
        cluster_slugs = [slugs[i] for i, m in enumerate(mask) if m]
        cluster_size = len(cluster_slugs)

        # Store cluster metadata
        cur = conn.execute(
            """INSERT INTO clusters (cluster_label, size, generated_at)
               VALUES (?, ?, datetime('now'))""",
            (int(label), cluster_size),
        )
        cluster_id = cur.lastrowid

        # Store memo assignments with membership probabilities
        probs = clusterer.probabilities_ if hasattr(clusterer, "probabilities_") else np.ones(len(labels))
        for i, slug in enumerate(slugs):
            if labels[i] == label:
                conn.execute(
                    """INSERT OR IGNORE INTO cluster_memos (cluster_id, memo_slug, membership_prob)
                       VALUES (?, ?, ?)""",
                    (cluster_id, slug, float(probs[i])),
                )

        cluster_count += 1

    conn.commit()
    return cluster_count


def _get_console():
    from rich.console import Console
    return Console()
