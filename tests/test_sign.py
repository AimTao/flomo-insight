"""Tests for MD5 signature builder (synthetic salt — no vendor constant)."""

from __future__ import annotations

import hashlib

import pytest

from flomo_insight.api.sign import (
    MissingSignSalt,
    build_memo_params,
    get_sign_salt,
    sign_params,
)

TEST_SALT = "unit-test-salt-not-vendor"


def _expected_sign(params: dict[str, str], salt: str) -> str:
    ordered = sorted(params.items())
    raw = "&".join(f"{k}={v}" for k, v in ordered) + salt
    return hashlib.md5(raw.encode()).hexdigest()


def test_sign_matches_md5_of_sorted_params_plus_salt():
    params = {"a": "1", "b": "2"}
    signed = sign_params(dict(params), salt=TEST_SALT)
    assert signed["sign"] == _expected_sign(params, TEST_SALT)


def test_get_sign_salt_prefers_env(monkeypatch):
    monkeypatch.setenv("FLOMO_SIGN_SALT", "env-salt-value-32chars-aaaaaaaa")
    assert get_sign_salt() == "env-salt-value-32chars-aaaaaaaa"


def test_get_sign_salt_raises_when_missing(monkeypatch):
    monkeypatch.delenv("FLOMO_SIGN_SALT", raising=False)
    monkeypatch.setattr(
        "flomo_insight.config.load_config",
        lambda: type("C", (), {"flomo_sign_salt": ""})(),
    )
    with pytest.raises(MissingSignSalt):
        get_sign_salt()


def test_sign_is_deterministic():
    params = {"a": "1", "b": "2"}
    s1 = sign_params(dict(params), salt=TEST_SALT)
    s2 = sign_params(dict(params), salt=TEST_SALT)
    assert s1["sign"] == s2["sign"]


def test_sign_independent_of_param_order():
    a = sign_params({"a": "1", "b": "2"}, salt=TEST_SALT)
    b = sign_params({"b": "2", "a": "1"}, salt=TEST_SALT)
    assert a["sign"] == b["sign"]


def test_sign_changes_with_value():
    a = sign_params({"a": "1"}, salt=TEST_SALT)
    b = sign_params({"a": "2"}, salt=TEST_SALT)
    assert a["sign"] != b["sign"]


def test_sign_appended_not_replaced():
    params = {"a": "1"}
    signed = sign_params(params, salt=TEST_SALT)
    assert "sign" in signed
    assert signed["a"] == "1"
    assert "sign" not in params


def test_build_memo_params_has_required_fields():
    p = build_memo_params(limit=200, salt=TEST_SALT)
    required = {"limit", "tz", "timestamp", "api_key", "app_version", "platform", "webp", "sign"}
    assert required.issubset(p.keys())
    assert p["limit"] == "200"
    assert p["api_key"] == "flomo_web"


def test_build_memo_params_pagination_fields():
    p = build_memo_params(latest_slug="SLUG", latest_updated_at="123", salt=TEST_SALT)
    assert p["latest_slug"] == "SLUG"
    assert p["latest_updated_at"] == "123"
    p2 = build_memo_params(salt=TEST_SALT)
    assert "latest_slug" not in p2
    assert "latest_updated_at" not in p2
