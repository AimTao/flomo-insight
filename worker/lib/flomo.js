/** Incremental flomo → D1 mirror helpers (pure pieces + fetch). */

import { buildMemoParams } from "./sign.js";

export function tsToIso(ts) {
  if (ts === null || ts === undefined || ts === "") return "";
  if (typeof ts === "number") return new Date(ts).toISOString();
  return String(ts);
}

export function parseTags(memo) {
  const tags = memo.tags || [];
  const out = [];
  for (const t of tags) {
    if (t && typeof t === "object" && t.name) out.push(t.name);
    else if (typeof t === "string") out.push(t);
  }
  if (out.length) return out;
  const content = memo.content || "";
  const raw = content.match(/#([^\s<#]+)/g) || [];
  return raw.map((x) => x.slice(1).replace(/[</p>.,;:!?，。；：！？]+$/, "")).filter(Boolean);
}

/**
 * Fetch one page from flomo. Returns { memos, nextSlug, nextUpdatedAt, done }.
 */
export async function fetchUpdatedPage(token, { limit = 200, latestSlug, latestUpdatedAt, salt } = {}) {
  const params = buildMemoParams({ limit, latestSlug, latestUpdatedAt, salt });
  const qs = new URLSearchParams(params).toString();
  const resp = await fetch(`https://flomoapp.com/api/v1/memo/updated/?${qs}`, {
    headers: {
      authorization: `Bearer ${token}`,
      "user-agent": "flomo-insight-worker/0.1",
      "x-requested-with": "XMLHttpRequest",
    },
  });
  if (!resp.ok) throw new Error(`flomo HTTP ${resp.status}`);
  const data = await resp.json();
  if (data.code !== 0) {
    const err = new Error(data.message || "flomo error");
    err.code = data.code;
    throw err;
  }
  const memos = data.data || [];
  let last = memos[memos.length - 1];
  if (last && !last.content) {
    for (let i = memos.length - 1; i >= 0; i--) {
      if (memos[i].content) {
        last = memos[i];
        break;
      }
    }
  }
  return {
    memos,
    nextSlug: last?.slug,
    nextUpdatedAt: last?.updated_at != null ? String(last.updated_at) : undefined,
    done: memos.length < limit,
  };
}

/** Walk all pages and return upserts/deletes for D1. Throttled between pages. */
export async function collectFlomoUpdates(token, cursor = {}, pageSize = 200, salt) {
  const upserts = [];
  const deletes = [];
  let latestSlug = cursor.latestSlug;
  let latestUpdatedAt = cursor.latestUpdatedAt;
  let pages = 0;

  for (;;) {
    const page = await fetchUpdatedPage(token, {
      limit: pageSize,
      latestSlug,
      latestUpdatedAt,
      salt,
    });
    pages += 1;
    for (const memo of page.memos) {
      if (memo.deleted_at || !memo.content) {
        if (memo.slug) deletes.push(memo.slug);
        continue;
      }
      upserts.push(memo);
    }
    if (page.nextSlug) latestSlug = page.nextSlug;
    if (page.nextUpdatedAt) latestUpdatedAt = page.nextUpdatedAt;
    if (page.done || pages > 50) break;
    // Anti-ban: pause between flomo pages (Workers setTimeout is ms)
    await new Promise((r) => setTimeout(r, 1200));
  }
  return { upserts, deletes, latestSlug, latestUpdatedAt };
}

/** Build SQL batch to upsert memos into D1 (content + tags archive). */
export function buildUpsertSql(upserts, now) {
  if (!upserts.length) return null;
  const values = upserts
    .map((m) => {
      const slug = String(m.slug).replace(/'/g, "''");
      const content = String(m.content || "").replace(/'/g, "''");
      const tags = parseTags(m).join(",").replace(/'/g, "''");
      const source = String(m.source || "flomo").replace(/'/g, "''");
      const created = tsToIso(m.created_at).replace(/'/g, "''");
      const updated = tsToIso(m.updated_at).replace(/'/g, "''");
      return `('${slug}','${content}','${tags}','${source}','${created}','${updated}','${now}')`;
    })
    .join(",");
  return (
    "INSERT INTO memos (slug, content, tags, source, created_at, updated_at, backed_up_at) " +
    `VALUES ${values} ON CONFLICT(slug) DO UPDATE SET ` +
    "content=excluded.content, tags=excluded.tags, source=excluded.source, " +
    "updated_at=excluded.updated_at, backed_up_at=excluded.backed_up_at"
  );
}

export function buildDeleteSql(slugs) {
  if (!slugs.length) return null;
  const list = slugs.map((s) => `'${String(s).replace(/'/g, "''")}'`).join(",");
  return `DELETE FROM memos WHERE slug IN (${list})`;
}
