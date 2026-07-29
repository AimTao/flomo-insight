export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const key = url.searchParams.get("key") || "";

    if (key !== env.REVIEW_KEY) {
      return new Response("Unauthorized", { status: 401 });
    }

    try {
      const r = await env.DB.prepare(
        "SELECT * FROM daily_reviews ORDER BY served_count ASC LIMIT 1"
      ).first();

      if (!r) {
        return new Response(JSON.stringify({ content: "No reviews yet", empty: true }), {
          headers: { "Content-Type": "application/json" }
        });
      }

      await env.DB.prepare(
        "UPDATE daily_reviews SET served_count = served_count + 1 WHERE id = ?1"
      ).bind(r.id).run();

      return new Response(JSON.stringify({
        content: r.content,
        date: r.date,
        id: r.id,
      }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" }
      });
    }
  },
};
