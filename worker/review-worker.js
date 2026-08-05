// Daily review worker — rotates review cards by served frequency.
//
// D1 `daily_reviews` table (built by `flomo review-push`):
//   id, slug, content (plain text note, tags stripped), date, served_count
//
// GET /?key=... → the least-served card. After serving, served_count +1.
//   Cards are served in round-robin frequency order — the more a card has
//   been shown, the less it gets picked. No due dates, no grading.
//
// The content is produced locally (cleaned from memos) and pushed via
// `flomo review-push`.

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const key = url.searchParams.get("key") || "";

    if (key !== env.REVIEW_KEY) {
      return new Response("Unauthorized", { status: 401 });
    }

    try {
      return await handleGet(env);
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: jsonHeaders(),
      });
    }
  },
};

async function handleGet(env) {
  const r = await env.DB.prepare(
    `SELECT * FROM daily_reviews
     ORDER BY served_count ASC, RANDOM()
     LIMIT 1`
  ).first();

  if (!r) {
    return new Response(
      JSON.stringify({ content: "No reviews yet", empty: true }),
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
      date: r.date,
      served: r.served_count + 1,
    }),
    { headers: jsonHeaders() }
  );
}

function jsonHeaders() {
  return {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
  };
}
