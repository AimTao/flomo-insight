import { buildMemoParams, md5, requireSalt, signParams } from "../lib/sign.js";
import assert from "node:assert/strict";
import test from "node:test";

const TEST_SALT = "unit-test-salt-not-vendor";

test("md5 known vector", () => {
  assert.equal(md5(""), "d41d8cd98f00b204e9800998ecf8427e");
  assert.equal(md5("abc"), "900150983cd24fb0d6963f7d28e17f72");
});

test("requireSalt throws when empty", () => {
  assert.throws(() => requireSalt(""), /FLOMO_SIGN_SALT/);
  assert.equal(requireSalt("  abc  "), "abc");
});

test("signParams uses provided salt", () => {
  const signed = signParams({ a: "1", b: "2" }, TEST_SALT);
  assert.equal(signed.sign.length, 32);
  const again = signParams({ b: "2", a: "1" }, TEST_SALT);
  assert.equal(signed.sign, again.sign);
  const other = signParams({ a: "1", b: "2" }, TEST_SALT + "x");
  assert.notEqual(signed.sign, other.sign);
});

test("buildMemoParams includes cursor and sign", () => {
  const p = buildMemoParams({
    limit: 50,
    latestSlug: "abc",
    latestUpdatedAt: "123",
    salt: TEST_SALT,
  });
  assert.equal(p.latest_slug, "abc");
  assert.equal(p.latest_updated_at, "123");
  assert.equal(p.limit, "50");
  assert.ok(p.sign && p.sign.length === 32);
});
