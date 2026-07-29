"""Daily review engine — overview + deep-dive for LLM-driven review generation.

SQL does raw aggregation only. No selection, no grouping, no truncation.
LLM decides everything: which pools to explore, which memos to group, what to write.
"""

from __future__ import annotations

import sqlite3
from typing import Any


# ── Phase 1: Overview (all pools, lightweight, no full content) ──────────────

def get_overview(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """Return an overview of ALL candidate pools across 4 strategies.

    Each pool entry: {label, total_memos, samples: [str], tag_distribution: {tag: count}}

    Returns everything — no LIMIT, no HAVING threshold. LLM decides what matters.
    """
    return {
        "same_book": _overview_books(conn),
        "tag_cluster": _overview_tags(conn),
        "near_time": _overview_dates(conn),
        "co_tag": _overview_co_tags(conn),
    }


def _overview_books(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("""
        SELECT w.book_title, COUNT(*) AS cnt, GROUP_CONCAT(m.slug) AS slugs
        FROM weread_imports w
        JOIN memos m ON m.slug = w.flomo_slug
        WHERE w.flomo_slug != ''
        GROUP BY w.book_title ORDER BY cnt DESC
    """).fetchall()

    pools = []
    for row in rows:
        slugs = row["slugs"].split(",")
        samples, tags = _sample_and_tags(conn, slugs, max_samples=3)
        pools.append({
            "label": row["book_title"],
            "total_memos": row["cnt"],
            "samples": samples,
            "tag_distribution": tags,
        })
    return pools


def _overview_tags(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("""
        SELECT t.name, COUNT(*) AS cnt, GROUP_CONCAT(m.slug) AS slugs
        FROM memo_tags mt
        JOIN tags t ON t.id = mt.tag_id
        JOIN memos m ON m.slug = mt.memo_slug
        GROUP BY t.name ORDER BY cnt DESC
    """).fetchall()

    pools = []
    for row in rows:
        slugs = row["slugs"].split(",")
        samples, tags = _sample_and_tags(conn, slugs, max_samples=3)
        pools.append({
            "label": row["name"],
            "total_memos": row["cnt"],
            "samples": samples,
            "tag_distribution": tags,
        })
    return pools


def _overview_dates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("""
        SELECT date(m.created_at) AS d, COUNT(*) AS cnt,
               GROUP_CONCAT(m.slug) AS slugs
        FROM memos m
        GROUP BY d ORDER BY cnt DESC
    """).fetchall()

    pools = []
    for row in rows:
        slugs = row["slugs"].split(",")
        samples, tags = _sample_and_tags(conn, slugs, max_samples=3)
        pools.append({
            "label": row["d"],
            "total_memos": row["cnt"],
            "samples": samples,
            "tag_distribution": tags,
        })
    return pools


def _overview_co_tags(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("""
        SELECT t1.name AS a, t2.name AS b, COUNT(*) AS w,
               GROUP_CONCAT(mt1.memo_slug) AS slugs
        FROM memo_tags mt1
        JOIN memo_tags mt2 ON mt1.memo_slug = mt2.memo_slug AND mt1.tag_id < mt2.tag_id
        JOIN tags t1 ON t1.id = mt1.tag_id
        JOIN tags t2 ON t2.id = mt2.tag_id
        GROUP BY t1.name, t2.name ORDER BY w DESC
    """).fetchall()

    pools = []
    for row in rows:
        slugs = row["slugs"].split(",")
        samples, tags = _sample_and_tags(conn, slugs, max_samples=3)
        pools.append({
            "label": f"{row['a']} × {row['b']}",
            "total_memos": row["w"],
            "samples": samples,
            "tag_distribution": tags,
        })
    return pools


def _sample_and_tags(
    conn: sqlite3.Connection,
    slugs: list[str],
    max_samples: int = 3,
) -> tuple[list[str], dict[str, int]]:
    """Return content samples + tag distribution for a set of slugs."""
    placeholders = ",".join("?" * len(slugs))
    rows = conn.execute(
        f"SELECT slug, content FROM memos WHERE slug IN ({placeholders}) LIMIT ?",
        (*slugs, max_samples),
    ).fetchall()
    samples = [_clean_sample(r["content"]) for r in rows]

    tag_rows = conn.execute(
        f"SELECT t.name, COUNT(*) AS n FROM memo_tags mt "
        f"JOIN tags t ON t.id = mt.tag_id "
        f"WHERE mt.memo_slug IN ({placeholders}) "
        f"GROUP BY t.name ORDER BY n DESC",
        tuple(slugs),
    ).fetchall()
    tag_dist = {tr["name"]: tr["n"] for tr in tag_rows}

    return samples, tag_dist


def _clean_sample(text: str) -> str:
    """Light cleanup + truncate for overview samples (not full content)."""
    t = text.replace("<br>", " ").replace("<p>", "").replace("</p>", " ")
    t = t.replace("\n", " ").strip()
    return t[:80] + ("..." if len(t) > 80 else "")


# ── Phase 2: Deep-dive (full content for one pool) ──────────────────────────

def get_pool(
    conn: sqlite3.Connection,
    strategy: str,
    label: str,
) -> dict[str, Any] | None:
    """Return ALL complete notes for a specific pool.

    Args:
        strategy: same_book | tag_cluster | near_time | co_tag
        label: exact label from overview (book title, tag name, date, "A × B")

    Returns: {label, total_memos, notes: [{slug, content, tags, date, source}]}
             or None if pool not found.
    """
    if strategy == "same_book":
        return _pool_by_book(conn, label)
    elif strategy == "tag_cluster":
        return _pool_by_tag(conn, label)
    elif strategy == "near_time":
        return _pool_by_date(conn, label)
    elif strategy == "co_tag":
        return _pool_by_co_tags(conn, label)
    return None


def _pool_by_book(conn: sqlite3.Connection, book_title: str) -> dict | None:
    slugs = conn.execute("""
        SELECT m.slug FROM memos m
        JOIN weread_imports w ON w.flomo_slug = m.slug
        WHERE w.book_title = ? ORDER BY m.created_at DESC
    """, (book_title,)).fetchall()
    if not slugs:
        return None
    slug_list = [r["slug"] for r in slugs]
    return {
        "label": book_title,
        "total_memos": len(slug_list),
        "notes": _fetch_pool_memos(conn, slug_list),
    }


def _pool_by_tag(conn: sqlite3.Connection, tag_name: str) -> dict | None:
    slugs = conn.execute("""
        SELECT m.slug FROM memos m
        JOIN memo_tags mt ON mt.memo_slug = m.slug
        JOIN tags t ON t.id = mt.tag_id
        WHERE t.name = ? ORDER BY m.created_at DESC
    """, (tag_name,)).fetchall()
    if not slugs:
        return None
    slug_list = [r["slug"] for r in slugs]
    return {
        "label": tag_name,
        "total_memos": len(slug_list),
        "notes": _fetch_pool_memos(conn, slug_list),
    }


def _pool_by_date(conn: sqlite3.Connection, date_str: str) -> dict | None:
    slugs = conn.execute("""
        SELECT slug FROM memos
        WHERE date(created_at) = ? ORDER BY created_at DESC
    """, (date_str,)).fetchall()
    if not slugs:
        return None
    slug_list = [r["slug"] for r in slugs]
    return {
        "label": date_str,
        "total_memos": len(slug_list),
        "notes": _fetch_pool_memos(conn, slug_list),
    }


def _pool_by_co_tags(conn: sqlite3.Connection, label: str) -> dict | None:
    """label format: 'A × B'"""
    parts = label.split(" × ")
    if len(parts) != 2:
        return None
    a, b = parts
    slugs = conn.execute("""
        SELECT m.slug FROM memos m
        JOIN memo_tags mt1 ON mt1.memo_slug = m.slug
        JOIN memo_tags mt2 ON mt2.memo_slug = m.slug
        JOIN tags t1 ON t1.id = mt1.tag_id
        JOIN tags t2 ON t2.id = mt2.tag_id
        WHERE t1.name = ? AND t2.name = ? AND mt1.tag_id < mt2.tag_id
        ORDER BY m.created_at DESC
    """, (a, b)).fetchall()
    if not slugs:
        return None
    slug_list = [r["slug"] for r in slugs]
    return {
        "label": label,
        "total_memos": len(slug_list),
        "notes": _fetch_pool_memos(conn, slug_list),
    }


def _fetch_pool_memos(
    conn: sqlite3.Connection,
    slugs: list[str],
) -> list[dict[str, Any]]:
    """Fetch full memo content + tags for a list of slugs."""
    if not slugs:
        return []
    placeholders = ",".join("?" * len(slugs))
    rows = conn.execute(
        f"SELECT slug, content, source, created_at FROM memos "
        f"WHERE slug IN ({placeholders}) ORDER BY created_at DESC",
        tuple(slugs),
    ).fetchall()

    tag_rows = conn.execute(
        f"SELECT mt.memo_slug, t.name FROM memo_tags mt "
        f"JOIN tags t ON t.id = mt.tag_id "
        f"WHERE mt.memo_slug IN ({placeholders})",
        tuple(slugs),
    ).fetchall()
    tag_map: dict[str, list[str]] = {}
    for tr in tag_rows:
        tag_map.setdefault(tr["memo_slug"], []).append(tr["name"])

    return [
        {
            "slug": r["slug"],
            "content": r["content"],
            "tags": tag_map.get(r["slug"], []),
            "date": (r["created_at"] or "")[:10],
            "source": r["source"],
        }
        for r in rows
    ]


# ── Legacy: random-grouping (--groups flag) ─────────────────────────────────

import random


def _clean(text: str, limit: int = 200) -> str:
    t = text.replace("<br>", "").replace("<p>", "").replace("</p>", "\n")
    t = t.replace("#微信读书 ", "").replace("#AI ", "").replace("#金句 ", "")
    t = t.replace("#书评 ", "").replace("#精读 ", "").replace("#社会学 ", "")
    return t.strip()[:limit]


def find_groups(conn: sqlite3.Connection, count_per_strategy: int = 50
                ) -> list[dict[str, Any]]:
    """Find related memo groups across 4 strategies. (LEGACY — use get_overview/get_pool instead.)

    Returns list of {slugs: [str], contents: [str], strategy: str, tags: [str]}.
    """
    groups: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()

    strategies = [
        (_by_same_book, count_per_strategy),
        (_by_tag_cluster, count_per_strategy),
        (_by_co_tag, count_per_strategy),
        (_by_near_time, count_per_strategy),
    ]

    for strategy_fn, target in strategies:
        collected = 0
        for _ in range(target * 3):
            if collected >= target:
                break
            group = strategy_fn(conn)
            if not group:
                continue
            slugs = [s for s, _ in group]
            key = frozenset(slugs)
            if key in seen or len(set(slugs)) < len(slugs):
                continue
            seen.add(key)
            groups.append({
                "slugs": slugs,
                "contents": [_clean(c) for _, c in group],
                "strategy": strategy_fn.__name__,
            })
            collected += 1

    random.shuffle(groups)
    return groups


def _by_same_book(conn: sqlite3.Connection) -> list[tuple[str, str]] | None:
    row = conn.execute("""
        SELECT w.book_title FROM weread_imports w
        WHERE w.flomo_slug != ''
        GROUP BY w.book_title HAVING COUNT(*) >= 2
        ORDER BY RANDOM() LIMIT 1
    """).fetchone()
    if not row:
        return None
    n = random.randint(2, 4)
    slugs = conn.execute("""
        SELECT m.slug, m.content FROM memos m
        JOIN weread_imports w ON w.flomo_slug = m.slug
        WHERE w.book_title = ? ORDER BY RANDOM() LIMIT ?
    """, (row["book_title"], n)).fetchall()
    return [(r["slug"], r["content"]) for r in slugs] if len(slugs) >= 2 else None


def _by_tag_cluster(conn: sqlite3.Connection) -> list[tuple[str, str]] | None:
    row = conn.execute("""
        SELECT t.name FROM tags t
        JOIN memo_tags mt ON mt.tag_id = t.id
        WHERE t.name NOT IN ('微信读书','FOMO','贪','记账','模板','测试')
        GROUP BY t.name HAVING COUNT(*) >= 3
        ORDER BY RANDOM() LIMIT 1
    """).fetchone()
    if not row:
        return None
    n = random.randint(2, 4)
    slugs = conn.execute("""
        SELECT m.slug, m.content FROM memos m
        JOIN memo_tags mt ON mt.memo_slug = m.slug
        JOIN tags t ON t.id = mt.tag_id
        WHERE t.name = ? ORDER BY RANDOM() LIMIT ?
    """, (row["name"], n)).fetchall()
    return [(r["slug"], r["content"]) for r in slugs] if len(slugs) >= 2 else None


def _by_near_time(conn: sqlite3.Connection) -> list[tuple[str, str]] | None:
    row = conn.execute("""
        SELECT date(created_at) as d, COUNT(*) as cnt
        FROM memos WHERE source != 'weread'
        GROUP BY d HAVING cnt >= 2
        ORDER BY RANDOM() LIMIT 1
    """).fetchone()
    if not row:
        return None
    n = random.randint(2, 4)
    slugs = conn.execute("""
        SELECT m.slug, m.content FROM memos m
        WHERE date(m.created_at) = ? AND m.source != 'weread'
        ORDER BY RANDOM() LIMIT ?
    """, (row["d"], n)).fetchall()
    return [(r["slug"], r["content"]) for r in slugs] if len(slugs) >= 2 else None


def _by_co_tag(conn: sqlite3.Connection) -> list[tuple[str, str]] | None:
    row = conn.execute("""
        SELECT t1.name AS a, t2.name AS b, COUNT(*) AS w
        FROM memo_tags mt1
        JOIN memo_tags mt2 ON mt1.memo_slug = mt2.memo_slug AND mt1.tag_id < mt2.tag_id
        JOIN tags t1 ON t1.id = mt1.tag_id
        JOIN tags t2 ON t2.id = mt2.tag_id
        WHERE t1.name != '微信读书' AND t2.name != '微信读书'
        GROUP BY t1.name, t2.name HAVING w >= 2
        ORDER BY RANDOM() LIMIT 1
    """).fetchone()
    if not row:
        return None
    n = random.randint(2, 4)
    slugs = conn.execute("""
        SELECT m.slug, m.content FROM memos m
        JOIN memo_tags mt1 ON mt1.memo_slug = m.slug
        JOIN memo_tags mt2 ON mt2.memo_slug = m.slug
        JOIN tags t1 ON t1.id = mt1.tag_id
        JOIN tags t2 ON t2.id = mt2.tag_id
        WHERE t1.name = ? AND t2.name = ? AND mt1.tag_id < mt2.tag_id
        ORDER BY RANDOM() LIMIT ?
    """, (row["a"], row["b"], n)).fetchall()
    return [(r["slug"], r["content"]) for r in slugs] if len(slugs) >= 2 else None
