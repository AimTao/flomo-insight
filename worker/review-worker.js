/**
 * flomo-review Worker
 *
 * fetch  — GET /?key=REVIEW_KEY[&kind=memo|insight|all]
 *          least-served card, served_count += 1
 * scheduled — cron: incremental flomo → D1.memos
 *             optional: weread reviewed highlights → flomo → D1
 *
 * Secrets: REVIEW_KEY, FLOMO_TOKEN, WEREAD_KEY (optional)
 * Binding: env.DB (D1)
 */

import { collectFlomoUpdates, buildUpsertSql, buildDeleteSql } from "./lib/flomo.js";

const MEMOS_DDL = `
CREATE TABLE IF NOT EXISTS memos (
    slug TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    source TEXT DEFAULT 'flomo',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    backed_up_at TEXT NOT NULL
);
`;

const REVIEWS_DDL = `
CREATE TABLE IF NOT EXISTS daily_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'memo',
    slug TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    insight_type TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    served_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
`;

const SYNC_STATE_DDL = `
CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const key = url.searchParams.get("key") || "";
    if (!env.REVIEW_KEY || key !== env.REVIEW_KEY) {
      return new Response("Unauthorized", { status: 401 });
    }
    try {
      return await handleReview(env, url.searchParams.get("kind") || "all");
    } catch (e) {
      return json({ error: e.message }, 500);
    }
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(runScheduled(env));
  },
};

async function handleReview(env, kind) {
  await env.DB.prepare(REVIEWS_DDL).run();

  let sql = `SELECT id, kind, slug, content, insight_type, date, served_count
             FROM daily_reviews`;
  const binds = [];
  if (kind && kind !== "all") {
    sql += " WHERE kind = ?1";
    binds.push(kind);
  }
  sql += " ORDER BY served_count ASC, RANDOM() LIMIT 1";

  const stmt = binds.length ? env.DB.prepare(sql).bind(...binds) : env.DB.prepare(sql);
  const r = await stmt.first();
  if (!r) {
    return json({ content: "No reviews yet", empty: true });
  }

  await env.DB.prepare(
    "UPDATE daily_reviews SET served_count = served_count + 1 WHERE id = ?1",
  )
    .bind(r.id)
    .run();

  return json({
    id: r.id,
    kind: r.kind || "memo",
    slug: r.slug,
    content: r.content,
    insight_type: r.insight_type || "",
    date: r.date,
    served: (r.served_count || 0) + 1,
  });
}

async function runScheduled(env) {
  await env.DB.prepare(MEMOS_DDL).run();
  await env.DB.prepare(SYNC_STATE_DDL).run();
  await env.DB.prepare(REVIEWS_DDL).run();

  const result = { flomo: null, weread: null, error: null };

  if (env.FLOMO_TOKEN) {
    try {
      result.flomo = await syncFlomoToD1(env);
    } catch (e) {
      result.error = `flomo: ${e.message}`;
    }
  }

  if (env.WEREAD_KEY && env.FLOMO_TOKEN) {
    try {
      result.weread = await syncWereadToFlomo(env);
    } catch (e) {
      result.error = (result.error ? result.error + "; " : "") + `weread: ${e.message}`;
    }
  }

  return result;
}

export async function syncFlomoToD1(env) {
  const slugRow = await env.DB.prepare(
    "SELECT value FROM sync_state WHERE key = 'latest_slug'",
  ).first();
  const tsRow = await env.DB.prepare(
    "SELECT value FROM sync_state WHERE key = 'latest_updated_at'",
  ).first();

  const collected = await collectFlomoUpdates(
    env.FLOMO_TOKEN,
    {
      latestSlug: slugRow?.value,
      latestUpdatedAt: tsRow?.value,
    },
    200,
    env.FLOMO_SIGN_SALT,
  );

  const now = String(Math.floor(Date.now() / 1000));
  let written = 0;
  const upsertSql = buildUpsertSql(collected.upserts, now);
  if (upsertSql) {
    // chunk to stay under D1 statement limits
    for (let i = 0; i < collected.upserts.length; i += 20) {
      const chunk = collected.upserts.slice(i, i + 20);
      const sql = buildUpsertSql(chunk, now);
      await env.DB.prepare(sql).run();
      written += chunk.length;
    }
  }
  const delSql = buildDeleteSql(collected.deletes);
  if (delSql) await env.DB.prepare(delSql).run();

  if (collected.latestSlug) {
    await env.DB.prepare(
      "INSERT INTO sync_state (key, value) VALUES ('latest_slug', ?1) " +
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    )
      .bind(collected.latestSlug)
      .run();
  }
  if (collected.latestUpdatedAt) {
    await env.DB.prepare(
      "INSERT INTO sync_state (key, value) VALUES ('latest_updated_at', ?1) " +
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    )
      .bind(collected.latestUpdatedAt)
      .run();
  }

  return { upserted: written, deleted: collected.deletes.length };
}

/**
 * Minimal weread auto-import: create flomo memos for reviewed highlights.
 * Dedup via D1 table weread_imports(review_id).
 * Only #微信读书 tag — LLM tagging stays local.
 */
export async function syncWereadToFlomo(env) {
  await env.DB.prepare(
    "CREATE TABLE IF NOT EXISTS weread_imports (" +
      "review_id TEXT PRIMARY KEY, book_id TEXT, book_title TEXT, " +
      "mark_text TEXT, flomo_slug TEXT, imported_at TEXT)",
  ).run();

  const notebooks = await wereadCall(env.WEREAD_KEY, "/user/notebooks", { count: 50 });
  const books = notebooks.books || [];
  let created = 0;

  for (const book of books.slice(0, 10)) {
    const bookId = book.bookId || book.book_id;
    const title = book.title || book.book?.title || "未命名";
    if (!bookId) continue;

    const bookmarksData = await wereadCall(env.WEREAD_KEY, "/book/bookmarklist", {
      bookId,
    });
    const reviewsData = await wereadCall(env.WEREAD_KEY, "/review/list/mine", {
      bookid: bookId,
      count: 50,
    });
    const bookmarks = bookmarksData.updated || [];
    const reviews = (reviewsData.reviews || []).map((e) => e.review || e);

    for (const review of reviews) {
      const reviewId = review.reviewId || review.review_id;
      if (!reviewId) continue;
      const exists = await env.DB.prepare(
        "SELECT review_id FROM weread_imports WHERE review_id = ?1",
      )
        .bind(reviewId)
        .first();
      if (exists) continue;

      const abstract = review.abstract || "";
      const contentReview = review.content || "";
      if (!contentReview || contentReview.trim().length < 5) continue;

      const mark =
        bookmarks.find((b) => (b.markText || b.mark_text) === abstract)?.markText ||
        abstract;
      const body =
        `#微信读书<br>${mark || ""} ——《${title}》<br><br>${contentReview}`;

      const createdRes = await createFlomoMemo(
        env.FLOMO_TOKEN,
        body,
        env.FLOMO_SIGN_SALT,
      );
      const slug = createdRes?.data?.slug || "";
      await env.DB.prepare(
        "INSERT INTO weread_imports (review_id, book_id, book_title, mark_text, flomo_slug, imported_at) " +
          "VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
      )
        .bind(reviewId, bookId, title, mark || "", slug, String(Date.now()))
        .run();

      if (slug && body) {
        const now = String(Math.floor(Date.now() / 1000));
        await env.DB.prepare(
          "INSERT INTO memos (slug, content, tags, source, created_at, updated_at, backed_up_at) " +
            "VALUES (?1, ?2, '微信读书', 'weread', ?3, ?3, ?4) " +
            "ON CONFLICT(slug) DO UPDATE SET content=excluded.content, tags=excluded.tags",
        )
          .bind(slug, body, now, now)
          .run();
      }
      created += 1;
    }
  }
  return { created };
}

async function wereadCall(key, apiName, params) {
  const resp = await fetch("https://i.weread.qq.com/api/agent/gateway", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      "User-Agent": "flomo-insight-worker/0.1",
    },
    body: JSON.stringify({ api_name: apiName, skill_version: "1.0.3", ...params }),
  });
  if (!resp.ok) throw new Error(`weread ${apiName} HTTP ${resp.status}`);
  return resp.json();
}

async function createFlomoMemo(token, content, salt) {
  const { buildCreatePayload } = await import("./lib/sign.js");
  const body = buildCreatePayload(content, "web", salt);
  const resp = await fetch("https://flomoapp.com/api/v1/memo", {
    method: "PUT",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json; charset=utf-8",
      "user-agent": "flomo-insight-worker/0.1",
      "x-requested-with": "XMLHttpRequest",
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`flomo create HTTP ${resp.status}`);
  const data = await resp.json();
  if (data.code !== 0) throw new Error(data.message || "flomo create failed");
  return data;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
