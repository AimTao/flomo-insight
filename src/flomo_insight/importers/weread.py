"""WeRead (微信读书) highlight importer.

Flow:
  1. Fetch bookshelf → get all books with highlights
  2. Fetch bookmarks per book → get individual highlights
  3. Filter out already-imported (dedup via weread_imports table)
  4. Return batch of highlights formatted for LLM classification
  5. Claude reads each, assigns tags (always including #微信读书),
     creates memos via flomo_create, marks as imported.

API reference: https://i.weread.qq.com (cookie-based auth)
"""

from __future__ import annotations

import time
from typing import Any

import httpx

WEREAD_BASE = "https://i.weread.qq.com"

WEREAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://weread.qq.com/",
}


class WereadClient:
    """HTTP client for the WeRead internal API (cookie auth)."""

    def __init__(self, cookie: str) -> None:
        self._client = httpx.Client(
            base_url=WEREAD_BASE,
            timeout=30.0,
            headers={**WEREAD_HEADERS, "Cookie": cookie},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WereadClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def get_shelf(self) -> list[dict[str, Any]]:
        """Fetch the bookshelf (all books with highlights)."""
        resp = self._client.get("/shelf/friendWeReads")
        resp.raise_for_status()
        data = resp.json()
        return data.get("books", data.get("shelf", []))

    def get_bookmarks(self, book_id: str) -> list[dict[str, Any]]:
        """Fetch all bookmarks/highlights for a book."""
        resp = self._client.get("/book/bookmarklist", params={"bookId": book_id})
        resp.raise_for_status()
        data = resp.json()
        return data.get("updated", [])

    def get_book_info(self, book_id: str) -> dict[str, Any]:
        """Fetch book metadata (title, author, cover)."""
        resp = self._client.get("/book/info", params={"bookId": book_id})
        resp.raise_for_status()
        return resp.json()

    def verify(self) -> bool:
        """Verify the cookie is valid."""
        try:
            self.get_shelf()
            return True
        except Exception:
            return False


# ── Import logic ─────────────────────────────────────────────────────────────


def fetch_unimported_highlights(
    client: WereadClient,
    conn: Any,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch highlights from WeRead that haven't been imported yet.

    Returns a list of {bookmark_id, book_title, book_id, author, mark_text, chapter}.
    """
    shelf = client.get_shelf()
    results: list[dict[str, Any]] = []

    # Get all already-imported bookmark IDs
    existing = set(
        row[0]
        for row in conn.execute("SELECT bookmark_id FROM weread_imports").fetchall()
    )

    for item in shelf:
        if len(results) >= limit:
            break

        book = item.get("book", item.get("bookInfo", {}))
        book_id = str(book.get("bookId", ""))
        if not book_id:
            continue

        title = book.get("title", "Unknown Book")
        author = book.get("author", "")

        # Skip if this book has no highlights
        has_highlights = (
            item.get("hasBookmark", 0)
            or item.get("bookmarkCount", 0)
            or item.get("highlightCount", 0)
        )
        if not has_highlights:
            continue

        try:
            bookmarks = client.get_bookmarks(book_id)
        except Exception:
            continue

        for bm in bookmarks:
            if len(results) >= limit:
                break

            bm_id = str(bm.get("bookmarkId", ""))
            if not bm_id or bm_id in existing:
                continue

            mark_text = bm.get("markText", bm.get("text", "")).strip()
            if not mark_text or len(mark_text) < 10:
                continue

            chapter = bm.get("chapterName", bm.get("chapter", {}).get("title", ""))
            create_time = bm.get("createTime", 0)

            results.append(
                {
                    "bookmark_id": bm_id,
                    "book_id": book_id,
                    "book_title": title,
                    "author": author,
                    "chapter": chapter,
                    "mark_text": mark_text,
                    "create_time": create_time,
                }
            )

        time.sleep(0.3)  # be gentle

    return results


def mark_imported(
    conn: Any,
    bookmark_id: str,
    book_id: str,
    book_title: str,
    mark_text: str,
    flomo_slug: str = "",
) -> None:
    """Record a highlight as imported."""
    conn.execute(
        """INSERT OR IGNORE INTO weread_imports (bookmark_id, book_id, book_title, mark_text, flomo_slug)
           VALUES (?, ?, ?, ?, ?)""",
        (bookmark_id, book_id, book_title, mark_text, flomo_slug),
    )
    conn.commit()


def build_import_prompt(highlights: list[dict[str, Any]]) -> str:
    """Build a system prompt + formatted highlights for Claude to classify and import."""

    if not highlights:
        return "No new highlights to import. All caught up! 📚"

    book_names = sorted(set(h["book_title"] for h in highlights))
    book_list = "\n".join(f"- {b}" for b in book_names)

    items: list[str] = []
    for i, h in enumerate(highlights):
        chapter = f"「{h['chapter']}」" if h["chapter"] else ""
        items.append(
            f"### #{i + 1} [{h['bookmark_id']}]\n"
            f"**书**: {h['book_title']}  {chapter}\n"
            f"**作者**: {h['author']}\n"
            f"**划线**: {h['mark_text']}"
        )

    items_text = "\n\n".join(items)

    return (
        f"# 微信读书划线导入\n\n"
        f"你需要将以下 {len(highlights)} 条微信读书划线逐条导入 flomo。\n\n"
        f"## 涉及书籍\n{book_list}\n\n"
        f"## 导入规则（必须遵守）\n"
        f"1. 每条划线创建一个 flomo memo，内容格式：\n"
        f"   划线内容\n\n"
        f"   ——《书名》作者\n"
        f"2. 每条必须打标签 **#微信读书**（这是硬性要求）\n"
        f"3. 根据划线内容，额外打 1-3 个分类标签（如 #认知 #思维 #习惯 #效率 #哲学 等）\n"
        f"4. 标签要具体、有区分度，不要全部写一样的\n"
        f"5. 调用 flomo_create 工具逐条创建，tags 参数包含 #微信读书 + 分类标签\n\n"
        f"## 划线列表\n{items_text}\n\n"
        f"---\n"
        f"请现在开始逐条导入。每导入一条，调用 flomo_create 工具创建 memo。\n"
        f"创建完成后报告导入结果。"
    )


def build_weread_stats(conn: Any) -> dict[str, Any]:
    """Return WeRead import statistics."""
    total = conn.execute("SELECT COUNT(*) FROM weread_imports").fetchone()[0]
    books = conn.execute(
        "SELECT book_title, COUNT(*) as cnt FROM weread_imports GROUP BY book_title ORDER BY cnt DESC"
    ).fetchall()
    return {
        "total_imported": total,
        "books": [{"title": b["book_title"], "count": b["cnt"]} for b in books],
    }
