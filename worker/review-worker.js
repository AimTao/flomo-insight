// Daily review worker — serves the next due card, accepts grade feedback.
//
// D1 `daily_reviews` table (new spaced-repetition schema):
//   id, slug, content (plain text note), hook, due_at (YYYY-MM-DD),
//   date (note creation date), served_count, created_at
//
// GET  /?key=...          → one card whose due_at <= today, least-served first
// POST /?key=...          → grade feedback {slug, grade}
//
// The due schedule is computed locally (flomo review-daily / grade) and
// pushed to D1 via `flomo review push-daily`. This worker just surfaces it.

const TZ = "Asia/Shanghai";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const key = url.searchParams.get("key") || "";

    if (key !== env.REVIEW_KEY) {
      return new Response("Unauthorized", { status: 401 });
    }

    const today = todayIn(TZ);

    try {
      if (request.method === "POST") {
        return await handleGrade(request, env, today);
      }
      return await handleGet(env, today);
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: jsonHeaders(),
      });
    }
  },
};

async function handleGet(env, today) {
  const r = await env.DB.prepare(
    `SELECT * FROM daily_reviews
     WHERE due_at <= ?1
     ORDER BY served_count ASC, due_at ASC
     LIMIT 1`
  )
    .bind(today)
    .first();

  if (!r) {
    return new Response(
      JSON.stringify({ content: "No reviews due today", empty: true }),
      { headers: jsonHeaders() }
    );
  }

  await env.DB.prepare(
    "UPDATE daily_reviews SET served_count = served_count + 1 WHERE id = ?1"
  )
    .bind(r.id)
    .run();

  return new Response(
    JSON.stringify({
      id: r.id,
      slug: r.slug,
      content: r.content,
      hook: r.hook || "",
      tags: r.tags ? JSON.parse(r.tags) : [],
      due: r.due_at,
    }),
    { headers: jsonHeaders() }
  );
}

async function handleGrade(request, env, today) {
  let body;
  try {
    body = await request.json();
  } catch {
    return new Response(JSON.stringify({ error: "invalid JSON" }), {
      status: 400,
      headers: jsonHeaders(),
    });
  }

  const { slug, grade } = body || {};
  if (!slug || !["again", "hard", "good", "easy"].includes(grade)) {
    return new Response(
      JSON.stringify({ error: "body needs {slug, grade}" }),
      { status: 400, headers: jsonHeaders() }
    );
  }

  const r = await env.DB.prepare(
    "SELECT id, interval_days FROM daily_reviews WHERE slug = ?1"
  )
    .bind(slug)
    .first();
  if (!r) {
    return new Response(JSON.stringify({ error: "unknown slug" }), {
      status: 404,
      headers: jsonHeaders(),
    });
  }

  // Mirror the simplified SM-2 from src/review/scheduler.py.
  const MUL = { again: 1.0, hard: 1.3, good: 2.0, easy: 3.0 };
  const prior = r.interval_days || 1;
  const interval =
    grade === "again" ? 1 : Math.min(60, Math.max(1, Math.round(prior * MUL[grade])));
  const nextDue = addDays(today, interval);

  await env.DB.prepare(
    `UPDATE daily_reviews
     SET interval_days = ?2, due_at = ?3, last_grade = ?4, served_count = 0
     WHERE id = ?1`
  )
    .bind(r.id, interval, nextDue, grade)
    .run();

  return new Response(
    JSON.stringify({ slug, grade, next_due: nextDue, interval_days: interval }),
    { headers: jsonHeaders() }
  );
}

// ── helpers ───────────────────────────────────────────────────────────────

function jsonHeaders() {
  return {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

function todayIn(tz) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function addDays(dateStr, days) {
  const d = new Date(dateStr + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
