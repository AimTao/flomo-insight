"""Local write-through helpers — call ONLY after flomo API succeeds."""

from __future__ import annotations

import re
from typing import Any


def apply_create_locally(conn: Any, memo: dict[str, Any]) -> None:
    """Mirror a flomo-created memo into SQLite (after cloud success)."""
    from flomo_insight.sync.exporter import _upsert_memo

    _upsert_memo(conn, memo)
    conn.commit()


def apply_update_locally(conn: Any, slug: str, content: str, updated_at: Any = None) -> None:
    """Mirror a successful flomo update into SQLite."""
    from flomo_insight.sync.exporter import _upsert_memo
    import time as _time

    ts = updated_at if updated_at is not None else int(_time.time() * 1000)
    tags = [{"name": t} for t in _extract_tags(content)]
    _upsert_memo(
        conn,
        {
            "slug": slug,
            "content": content,
            "raw_content": content,
            "source": "flomo",
            "created_at": ts,
            "updated_at": ts,
            "tags": tags,
        },
    )
    conn.commit()


def apply_delete_locally(conn: Any, slug: str) -> None:
    """Mirror a successful flomo delete into SQLite."""
    from flomo_insight.sync.exporter import _delete_memo

    _delete_memo(conn, slug)
    conn.commit()


def list_local_pending(conn: Any, limit: int = 100) -> list[dict[str, Any]]:
    """Memos marked source='local' — not yet created on flomo via push."""
    rows = conn.execute(
        "SELECT slug, content, created_at, updated_at FROM memos "
        "WHERE source = 'local' ORDER BY created_at ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "slug": r["slug"],
            "content": r["content"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def push_local_pending(
    conn: Any,
    client: Any,
    limit: int = 20,
) -> dict[str, Any]:
    """Create source=local memos on flomo, then replace local rows with cloud slug.

    Write order: flomo create first; only on success mirror SQLite.
    """
    from flomo_insight.sync.exporter import _delete_memo

    pending = list_local_pending(conn, limit=limit)
    pushed = 0
    errors: list[str] = []
    slugs: list[str] = []

    for item in pending:
        old_slug = item["slug"]
        content = item["content"]
        try:
            result = client.create_memo(content)
        except Exception as e:  # keep going; report at end
            errors.append(f"{old_slug}: {e}")
            continue

        data = (result or {}).get("data") or {}
        new_slug = data.get("slug") or ""
        if not new_slug:
            errors.append(f"{old_slug}: flomo did not return slug")
            continue

        _delete_memo(conn, old_slug)
        memo = dict(data)
        memo.setdefault("slug", new_slug)
        memo.setdefault("content", content)
        memo.setdefault("source", "flomo")
        apply_create_locally(conn, memo)
        pushed += 1
        slugs.append(new_slug)

    return {"pushed": pushed, "slugs": slugs, "errors": errors, "pending": len(pending)}


def _extract_tags(content: str) -> list[str]:
    raw = re.findall(r"#([^\s<#]+)", content or "")
    return [t.rstrip("</p>.,;:!?，。；：！？") for t in raw if t]
