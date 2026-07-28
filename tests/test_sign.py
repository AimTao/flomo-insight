"""Tests for MD5 signature builder."""

from src.api.sign import SALT, sign_params, build_memo_params


def test_sign_matches_known_real_request():
    """The signature must match a sign captured from a real flomo web request."""
    from tests.conftest import KNOWN_SIGN, KNOWN_SIGN_PARAMS

    signed = sign_params(dict(KNOWN_SIGN_PARAMS))
    assert signed["sign"] == KNOWN_SIGN, (
        f"Expected {KNOWN_SIGN}, got {signed['sign']}. "
        "If flomo rotated the salt, update SALT in src/api/sign.py."
    )


def test_sign_is_deterministic():
    """Same input → same sign."""
    params = {"a": "1", "b": "2"}
    s1 = sign_params(dict(params))
    s2 = sign_params(dict(params))
    assert s1["sign"] == s2["sign"]


def test_sign_independent_of_param_order():
    """Sign must be order-independent (sorted internally)."""
    a = sign_params({"a": "1", "b": "2"})
    b = sign_params({"b": "2", "a": "1"})
    assert a["sign"] == b["sign"]


def test_sign_changes_with_value():
    """Different value → different sign."""
    a = sign_params({"a": "1"})
    b = sign_params({"a": "2"})
    assert a["sign"] != b["sign"]


def test_sign_appended_not_replaced():
    """sign_params returns a copy with 'sign' added, original params intact."""
    params = {"a": "1"}
    signed = sign_params(params)
    assert "sign" in signed
    assert signed["a"] == "1"
    # original dict unchanged
    assert "sign" not in params


def test_build_memo_params_has_required_fields():
    """build_memo_params must include all fields flomo expects + sign."""
    p = build_memo_params(limit=200)
    required = {"limit", "tz", "timestamp", "api_key", "app_version", "platform", "webp", "sign"}
    assert required.issubset(p.keys())
    assert p["limit"] == "200"
    assert p["api_key"] == "flomo_web"


def test_build_memo_params_pagination_fields():
    """Pagination cursor fields added only when provided."""
    p = build_memo_params(latest_slug="SLUG", latest_updated_at="123")
    assert p["latest_slug"] == "SLUG"
    assert p["latest_updated_at"] == "123"

    p2 = build_memo_params()
    assert "latest_slug" not in p2
    assert "latest_updated_at" not in p2


def test_salt_is_nonempty_constant():
    """Guard against accidentally clearing the salt."""
    assert SALT and len(SALT) == 32
