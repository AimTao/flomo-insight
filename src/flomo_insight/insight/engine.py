"""Insight generation engine — data-derived, template-based + LLM perspectives.

Statistical insights (topics/stagnant/declining/connections/draft) are template-based.
Perspective insights (default/value-clarification/inversion/cbt/mbti/second-order)
fetch notes and wrap them with a system prompt for Claude Code to interpret.
"""

from __future__ import annotations

import json
import sqlite3


def generate_insight(conn: sqlite3.Connection, insight_type: str, **kwargs) -> str:
    """Generate an insight of the specified type. Raises ValueError if data missing.

    Statistical types: topics, stagnant, declining, connections, draft
    Perspective types: perspective (requires lens param, e.g. lens="cbt")
    """
    statistical = {
        "topics": _insight_topics,
        "stagnant": _insight_stagnant,
        "declining": _insight_declining,
        "connections": _insight_connections,
        "draft": _insight_draft,
    }

    if insight_type in statistical:
        return statistical[insight_type](conn)

    if insight_type == "perspective":
        lens = kwargs.get("lens", "default")
        return _insight_perspective(conn, lens)

    valid = ", ".join(list(statistical.keys()) + ["perspective"])
    raise ValueError(f"Unknown insight type: {insight_type}. Valid: {valid}")


def _insight_perspective(conn: sqlite3.Connection, lens: str) -> str:
    """Fetch notes and wrap with a perspective prompt for LLM analysis."""
    from flomo_insight.insight.templates import fetch_notes_for_perspective

    return fetch_notes_for_perspective(conn, lens)


def _insight_topics(conn: sqlite3.Connection) -> str:
    """What topics do you think about most?"""
    clusters = conn.execute(
        """SELECT id, cluster_label, keywords, size
           FROM clusters WHERE cluster_label != -1
           ORDER BY size DESC LIMIT 8"""
    ).fetchall()

    if not clusters:
        raise ValueError("No clusters found. Run 'flomo analyze' first.")

    total = conn.execute(
        "SELECT COUNT(*) FROM cluster_memos WHERE cluster_id IN (SELECT id FROM clusters WHERE cluster_label != -1)"
    ).fetchone()[0]

    lines = ["## 📊 Your Top Thinking Topics\n"]
    for i, c in enumerate(clusters):
        keywords = json.loads(c["keywords"]) if c["keywords"] else []
        kw_str = ", ".join(keywords[:5]) if keywords else "(untitled)"
        pct = (c["size"] / total * 100) if total > 0 else 0
        lines.append(f"**{i+1}. {kw_str}**  ")
        lines.append(f"   {c['size']} memos ({pct:.0f}% of total)\n")

    if total == 0:
        lines.append("_No clustered memos yet. Run `flomo analyze` first._")

    return "\n".join(lines)


def _insight_stagnant(conn: sqlite3.Connection) -> str:
    """Ideas that appear repeatedly but may lack follow-through."""
    # Find memos whose content is highly similar (same cluster) but
    # span a wide time range without actionable tags
    clusters = conn.execute(
        "SELECT id, keywords FROM clusters WHERE cluster_label != -1 AND size >= 3"
    ).fetchall()

    if not clusters:
        raise ValueError("No clusters found. Run 'flomo analyze' first.")

    lines = ["## 🔁 Recurring Ideas (Potential Stagnation)\n"]

    found = 0
    for c in clusters:
        # Get time span of this cluster
        row = conn.execute(
            """SELECT MIN(m.created_at) as first, MAX(m.created_at) as last, COUNT(*) as cnt
               FROM memos m
               JOIN cluster_memos cm ON cm.memo_slug = m.slug
               WHERE cm.cluster_id = ?""",
            (c["id"],),
        ).fetchone()

        if not row or not row["first"]:
            continue

        from datetime import datetime
        try:
            first = datetime.fromisoformat(row["first"])
            last = datetime.fromisoformat(row["last"])
        except (ValueError, TypeError):
            continue

        span_days = (last - first).days
        if span_days < 60 or row["cnt"] < 3:
            continue

        keywords = json.loads(c["keywords"]) if c["keywords"] else ["(untitled)"]
        kw_str = ", ".join(keywords[:3])

        lines.append(f"**{kw_str}**")
        lines.append(f"  {row['cnt']} notes over {span_days} days — first: {first.strftime('%Y-%m-%d')}, last: {last.strftime('%Y-%m-%d')}")
        lines.append(f"  Consider: Is this something you want to act on?\n")
        found += 1

        if found >= 5:
            break

    if found == 0:
        lines.append("_No stagnant patterns detected. Your thinking seems well-distributed._")

    return "\n".join(lines)


def _insight_declining(conn: sqlite3.Connection) -> str:
    """Topics that are losing interest over time."""
    clusters = conn.execute(
        """SELECT c.id, c.keywords, tt.trend_slope, c.size
           FROM clusters c
           JOIN topic_trends tt ON tt.cluster_id = c.id
           WHERE c.cluster_label != -1
           GROUP BY c.id
           HAVING tt.trend_slope < -0.05
           ORDER BY tt.trend_slope ASC
           LIMIT 6"""
    ).fetchall()

    if not clusters:
        raise ValueError("No trend data found. Run 'flomo analyze' first.")

    lines = ["## 📉 Declining Topics\n"]
    lines.append("These topics appear less frequently over time:\n")

    for c in clusters:
        keywords = json.loads(c["keywords"]) if c["keywords"] else ["(untitled)"]
        kw_str = ", ".join(keywords[:3])
        slope = c["trend_slope"]
        lines.append(f"- **{kw_str}** — trend: {slope:+.2f}/month ({c['size']} total memos)")

    if len(clusters) == 0:
        lines.append("_No declining topics detected. Your interests are stable or growing._")

    return "\n".join(lines)


def _insight_connections(conn: sqlite3.Connection) -> str:
    """Hidden connections between seemingly unrelated topics (via tag bridges)."""
    # Find tag pairs with high co-occurrence but different clusters
    rows = conn.execute(
        """SELECT t1.name AS tag_a, t2.name AS tag_b, tc.weight
           FROM tag_cooccurrence tc
           JOIN tags t1 ON t1.id = tc.tag_a_id
           JOIN tags t2 ON t2.id = tc.tag_b_id
           ORDER BY tc.weight DESC
           LIMIT 15"""
    ).fetchall()

    if not rows:
        raise ValueError("No co-occurrence data found. Run 'flomo analyze' first.")

    lines = ["## 🔗 Hidden Tag Connections\n"]
    lines.append("Tags that frequently appear together:\n")

    for r in rows:
        lines.append(f"- **#{r['tag_a']}** ↔ **#{r['tag_b']}** — {r['weight']} shared memos")

    lines.append("\n💡 *Try exploring these connections by searching across both tags.*")
    return "\n".join(lines)


def _insight_draft(conn: sqlite3.Connection) -> str:
    """Generate a writing draft from the largest cluster."""
    clusters = conn.execute(
        """SELECT id, keywords, size FROM clusters
           WHERE cluster_label != -1
           ORDER BY size DESC LIMIT 1"""
    ).fetchall()

    if not clusters:
        raise ValueError("No clusters found. Run 'flomo analyze' first.")

    c = clusters[0]
    keywords = json.loads(c["keywords"]) if c["keywords"] else ["Notes"]
    topic_title = keywords[0] if keywords else "Untitled"

    # Get memos in this cluster, chronological
    memos = conn.execute(
        """SELECT m.content, m.created_at
           FROM memos m
           JOIN cluster_memos cm ON cm.memo_slug = m.slug
           WHERE cm.cluster_id = ?
           ORDER BY m.created_at ASC
           LIMIT 15""",
        (c["id"],),
    ).fetchall()

    lines = [f"## ✍️ Writing Draft: {topic_title}\n"]
    lines.append(f"_Auto-generated from {c['size']} related notes._\n")

    # Extract first meaningful sentence from each memo
    for i, m in enumerate(memos):
        content = m["content"].strip()
        # Get the first non-empty line as a bullet point
        first_line = ""
        for line in content.split("\n"):
            clean = line.strip()
            if clean and len(clean) > 10:
                first_line = clean
                break
        if not first_line:
            first_line = content[:80]

        date = m["created_at"][:10] if m["created_at"] else ""
        lines.append(f"{i+1}. [{date}] {first_line}")

    lines.append(f"\n---")
    lines.append(f"*{c['size']} memos total in this topic. Expand in Claude Code for a full article.*")
    return "\n".join(lines)
