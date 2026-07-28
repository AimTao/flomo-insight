"""Topic trend analysis — detects rising and declining topics over time."""

from __future__ import annotations

import sqlite3
from collections import defaultdict


def compute_trends(conn: sqlite3.Connection) -> int:
    """Compute per-cluster monthly memo counts and linear trend slopes.

    Returns the number of trend entries created.
    """
    conn.execute("DELETE FROM topic_trends")
    conn.commit()

    # Get all clusters
    clusters = conn.execute("SELECT id, cluster_label FROM clusters").fetchall()
    if not clusters:
        return 0

    total = 0

    for cluster_row in clusters:
        cluster_id = cluster_row["id"]

        # Get memos in this cluster with their created_at dates
        rows = conn.execute(
            """SELECT m.created_at
               FROM memos m
               JOIN cluster_memos cm ON cm.memo_slug = m.slug
               WHERE cm.cluster_id = ?
               ORDER BY m.created_at""",
            (cluster_id,),
        ).fetchall()

        if not rows:
            continue

        # Count memos per month
        monthly: dict[str, int] = defaultdict(int)
        for row in rows:
            month = row["created_at"][:7]  # "2025-07"
            monthly[month] += 1

        # Compute linear regression on month index vs count
        months = sorted(monthly.keys())
        if len(months) >= 3:
            import numpy as np
            from scipy import stats

            x = np.arange(len(months))
            y = np.array([monthly[m] for m in months])
            slope, _, r_value, _, _ = stats.linregress(x, y)
        else:
            slope = 0.0

        # Store each month
        for month, count in monthly.items():
            conn.execute(
                """INSERT INTO topic_trends (cluster_id, month, memo_count, trend_slope)
                   VALUES (?, ?, ?, ?)""",
                (cluster_id, month, count, slope),
            )
            total += 1

    conn.commit()
    return total
