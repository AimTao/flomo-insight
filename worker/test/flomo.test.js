import { buildUpsertSql, buildDeleteSql, parseTags, tsToIso } from "../lib/flomo.js";
import assert from "node:assert/strict";
import test from "node:test";

test("tsToIso number and string", () => {
  assert.ok(tsToIso(1700000000000).includes("2023"));
  assert.equal(tsToIso("abc"), "abc");
  assert.equal(tsToIso(null), "");
});

test("parseTags from list and from content", () => {
  assert.deepEqual(parseTags({ tags: [{ name: "AI" }] }), ["AI"]);
  assert.deepEqual(parseTags({ content: "<p>#效率 两分钟</p>" }), ["效率"]);
});

test("buildUpsertSql escapes quotes, includes tags, upserts", () => {
  const sql = buildUpsertSql(
    [{ slug: "a1", content: "it's ok", tags: [{ name: "AI" }], source: "flomo", created_at: 1, updated_at: 2 }],
    "99",
  );
  assert.ok(sql.includes("INSERT INTO memos"));
  assert.ok(sql.includes("it''s ok"));
  assert.ok(sql.includes("tags"));
  assert.ok(sql.includes("'AI'"));
  assert.ok(sql.includes("ON CONFLICT(slug) DO UPDATE"));
  assert.ok(sql.includes("'99'"));
});

test("buildDeleteSql", () => {
  const sql = buildDeleteSql(["a", "b"]);
  assert.ok(sql.includes("DELETE FROM memos"));
  assert.ok(sql.includes("'a'"));
  assert.equal(buildDeleteSql([]), null);
});
