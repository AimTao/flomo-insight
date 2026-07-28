"""WeRead (微信读书) highlight+review importer via official Skills API.

Uses the official WeRead Skills API (https://weread.qq.com/r/weread-skills).
API key format: wrk-xxxxxxxx

Flow:
  1. /user/notebooks → find books with highlights and reviews
  2. /book/bookmarklist per book → get highlight text
  3. /review/list/mine per book → get personal reviews (书评/想法)
  4. Match reviews to highlights by position range
  5. Return batch of matched pairs for LLM classification
  6. Claude reads each pair, assigns tags (always including #微信读书),
     creates memos via flomo_create, marks as imported.

API: POST https://i.weread.qq.com/api/agent/gateway
Auth: Authorization: Bearer wrk-xxxxxxxx
Body: {"api_name": "/user/notebooks", "skill_version": "1.0.3", ...params}
"""

from __future__ import annotations

import time
from typing import Any

import httpx

GATEWAY_URL = "https://i.weread.qq.com/api/agent/gateway"
SKILL_VERSION = "1.0.3"
TIMEOUT = 30.0


class WereadClient:
    """HTTP client for the official WeRead Skills API."""

    def __init__(self, api_key: str) -> None:
        self._client = httpx.Client(
            base_url=GATEWAY_URL,
            timeout=TIMEOUT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "flomo-insight/0.1.0",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WereadClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _call(self, api_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a gateway API call."""
        body: dict[str, Any] = {
            "api_name": api_name,
            "skill_version": SKILL_VERSION,
        }
        if params:
            body.update(params)
        resp = self._client.post("", json=body)
        resp.raise_for_status()
        return resp.json()

    # ── API methods ──────────────────────────────────────────────────────

    def get_notebooks(self) -> list[dict[str, Any]]:
        """Get all books with notes (highlights + reviews)."""
        data = self._call("/user/notebooks", {"count": 200})
        return data.get("books", [])

    def get_bookmarks(self, book_id: str) -> list[dict[str, Any]]:
        """Get all highlights for a book."""
        data = self._call("/book/bookmarklist", {"bookId": book_id})
        return data.get("updated", [])

    def get_reviews(self, book_id: str) -> list[dict[str, Any]]:
        """Get all personal reviews/thoughts for a book.

        Paginates automatically. Returns list of review dicts.
        """
        reviews: list[dict[str, Any]] = []
        synckey: int = 0

        while True:
            params: dict[str, Any] = {"bookid": book_id, "count": 50}
            if synckey:
                params["synckey"] = synckey
            data = self._call("/review/list/mine", params)
            batch = data.get("reviews", [])
            for entry in batch:
                r = entry.get("review", entry)
                reviews.append(r)

            if not data.get("hasMore"):
                break
            synckey = data.get("synckey", 0)
            time.sleep(0.2)

        return reviews

    def verify(self) -> bool:
        """Verify the API key is valid."""
        try:
            self._call("/user/notebooks", {"count": 1})
            return True
        except Exception:
            return False


# ── Import logic ─────────────────────────────────────────────────────────────


def fetch_reviewed_highlights(
    client: WereadClient,
    conn: Any,
    batch_size: int = 15,
) -> list[dict[str, Any]]:
    """Fetch highlights that have personal reviews attached.

    Returns list of {review_id, bookmark_id, book_title, author, chapter,
    mark_text, review_text, create_time}.
    """
    notebooks = client.get_notebooks()
    results: list[dict[str, Any]] = []

    existing = set(
        row[0]
        for row in conn.execute("SELECT review_id FROM weread_imports").fetchall()
    )

    for nb in notebooks:
        if len(results) >= batch_size:
            break

        book = nb.get("book", {})
        book_id = str(book.get("bookId", ""))
        if not book_id:
            continue

        has_highlights = nb.get("noteCount", 0) > 0
        has_reviews = nb.get("reviewCount", 0) > 0

        # Need both highlights and reviews
        if not has_highlights or not has_reviews:
            continue

        title = book.get("title", "Unknown Book")
        author = book.get("author", "")

        # Fetch highlights and reviews
        try:
            bookmarks = client.get_bookmarks(book_id)
        except Exception:
            continue
        time.sleep(0.2)

        try:
            reviews = client.get_reviews(book_id)
        except Exception:
            reviews = []

        if not bookmarks or not reviews:
            continue

        # Build range → bookmark lookup
        bm_by_range: dict[str, dict[str, Any]] = {}
        for bm in bookmarks:
            rng = str(bm.get("range", ""))
            if rng:
                bm_by_range[rng] = bm

        # Match reviews to highlights by range
        for rv in reviews:
            if len(results) >= batch_size:
                break

            review_id = str(rv.get("reviewId", ""))
            if not review_id or review_id in existing:
                continue

            review_text = (rv.get("content") or "").strip()
            if not review_text:
                continue

            # Try to match to a highlight via range
            rng = str(rv.get("range", ""))
            bm = bm_by_range.get(rng)

            if bm:
                mark_text = (bm.get("markText") or "").strip()
                chapter = rv.get("chapterName", "")
                bm_id = str(bm.get("bookmarkId", ""))
            else:
                # Review without a matched highlight — use abstract as mark text
                abstract = (rv.get("abstract") or "").strip()
                if not abstract:
                    continue
                mark_text = abstract
                chapter = rv.get("chapterName", "")
                bm_id = ""

            if len(mark_text) < 5:
                continue

            results.append(
                {
                    "review_id": review_id,
                    "bookmark_id": bm_id,
                    "book_id": book_id,
                    "book_title": title,
                    "author": author,
                    "chapter": chapter,
                    "mark_text": mark_text,
                    "review_text": review_text,
                    "create_time": rv.get("createTime", 0),
                }
            )

    return results


def mark_imported(
    conn: Any,
    review_id: str,
    book_id: str,
    book_title: str,
    mark_text: str,
    flomo_slug: str = "",
) -> None:
    """Record a reviewed highlight as imported."""
    conn.execute(
        """INSERT OR IGNORE INTO weread_imports (review_id, book_id, book_title, mark_text, flomo_slug)
           VALUES (?, ?, ?, ?, ?)""",
        (review_id, book_id, book_title, mark_text, flomo_slug),
    )
    conn.commit()


def auto_import(
    weread_client: WereadClient,
    flomo_client: Any,
    conn: Any,
    batch_size: int = 15,
    classifier: Any = None,
) -> dict[str, Any]:
    """Automatically import reviewed highlights to flomo, one by one.

    Args:
        weread_client: Authenticated WeRead client.
        flomo_client: Authenticated FlomoClient (must have create_memo method).
        conn: SQLite connection for dedup tracking.
        batch_size: How many highlights to process.
        classifier: Optional callable(text, book_title) -> list[str] of tags.
                    If None, only #微信读书 is applied.

    Returns: {"imported": int, "skipped": int, "errors": list[str]}
    """
    items = fetch_reviewed_highlights(weread_client, conn, batch_size=batch_size)
    result = {"imported": 0, "skipped": 0, "errors": []}

    for item in items:
        try:
            # Build memo content
            chapter = f"「{item['chapter']}」" if item["chapter"] else ""
            content = (
                f"> {item['mark_text']}\n\n"
                f"{item['review_text']}\n\n"
                f"——《{item['book_title']}》{item['author']}"
            )

            # Determine tags
            tags = ["微信读书"]
            if classifier:
                extra = classifier(item["mark_text"] + " " + item["review_text"], item["book_title"])
                if extra:
                    tags.extend(extra)

            # Create in flomo
            resp = flomo_client.create_memo(content, tags=tags, source="weread")
            slug = resp.get("data", {}).get("slug", "")

            # Mark as imported
            mark_imported(
                conn, item["review_id"], item["book_id"],
                item["book_title"], item["mark_text"], slug,
            )
            result["imported"] += 1
            time.sleep(1.0)  # rate limit on flomo writes

        except Exception as e:
            result["errors"].append(f"Failed to import {item['review_id']}: {e}")
            result["skipped"] += 1

    return result


def build_import_prompt(items: list[dict[str, Any]]) -> str:
    """Build a system prompt + formatted highlights+reviews for Claude."""

    if not items:
        return "No new reviewed highlights to import. All caught up! 📚"

    item_texts: list[str] = []
    for i, h in enumerate(items):
        chapter = f"「{h['chapter']}」" if h["chapter"] else ""
        item_texts.append(
            f"### #{i + 1} [review:{h['review_id']}]\n"
            f"**书**: {h['book_title']}  作者: {h['author']}  {chapter}\n"
            f"**划线**: {h['mark_text']}\n"
            f"**书评**: {h['review_text']}"
        )

    items_block = "\n\n".join(item_texts)

    return (
        f"# 微信读书划线+书评导入\n\n"
        f"你需要将以下 {len(items)} 条「划线 + 书评」逐条导入 flomo。\n"
        f"每条都是你读过的书中的划线，以及你针对该划线写的书评/想法。\n\n"
        f"## 导入规则（必须遵守）\n"
        f"1. 每条创建一个 flomo memo，内容格式：\n"
        f"```\n"
        f"> 划线内容\n"
        f"\n"
        f"书评内容\n"
        f"\n"
        f"——《书名》作者\n"
        f"```\n"
        f"2. 每条必须打标签 **#微信读书**（硬性要求）\n"
        f"3. 根据划线内容和书评内容，额外打 1-3 个分类标签\n"
        f"   （如 #认知 #思维 #心理学 #管理 #效率 #哲学 #文学 #历史 等）\n"
        f"4. 标签要具体、有区分度，不同书的标签应该不同\n"
        f"5. 调用 flomo_create 逐条创建，tags 包含 #微信读书 + 分类标签\n"
        f"6. 创建后调用 flomo_weread_mark_imported 标记已导入\n\n"
        f"## 划线+书评列表\n\n"
        f"{items_block}\n\n"
        f"---\n"
        f"请现在开始逐条导入。"
    )


def build_weread_stats(conn: Any) -> dict[str, Any]:
    """Return WeRead import statistics."""
    total = conn.execute("SELECT COUNT(*) FROM weread_imports").fetchone()[0]
    books = conn.execute(
        "SELECT book_title, COUNT(*) as cnt FROM weread_imports "
        "GROUP BY book_title ORDER BY cnt DESC"
    ).fetchall()
    return {
        "total_imported": total,
        "books": [{"title": b["book_title"], "count": b["cnt"]} for b in books],
    }
