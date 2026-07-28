"""Tests for error handling: auth errors, retries, rate limit."""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import MagicMock, patch

from src.api.client import FlomoClient, FlomoAPIError, FlomoAuthError


def _make_client():
    """Client with a dummy token — no real requests will be made."""
    return FlomoClient("dummy-token")


def test_auth_error_not_retried():
    """Auth errors (code -10) should raise immediately, no retry."""
    client = _make_client()
    auth_response = httpx.Response(
        200, json={"code": -10, "message": "请先登录"},
        request=httpx.Request("GET", "https://flomoapp.com/api/v1/memo/updated/")
    )

    call_count = {"n": 0}
    def fake_request(*args, **kwargs):
        call_count["n"] += 1
        return auth_response

    with patch.object(client._client, "request", side_effect=fake_request):
        with pytest.raises(FlomoAuthError) as exc_info:
            client.get_updated(limit=1)

    # Must have called only once — no retry on auth errors
    assert call_count["n"] == 1
    assert "expired" in str(exc_info.value).lower() or "token" in str(exc_info.value).lower()


def test_network_error_retries_then_raises():
    """Network timeouts should retry MAX_RETRIES times then raise."""
    client = _make_client()

    call_count = {"n": 0}
    def fake_request(*args, **kwargs):
        call_count["n"] += 1
        raise httpx.TimeoutException("timed out")

    with patch.object(client._client, "request", side_effect=fake_request):
        with patch("src.api.client.time.sleep"):  # skip real sleeps
            with pytest.raises(httpx.TimeoutException):
                client.get_updated(limit=1)

    assert call_count["n"] == 3  # MAX_RETRIES


def test_success_after_one_retry():
    """If first call times out but second succeeds, return the data."""
    client = _make_client()

    success_response = httpx.Response(
        200, json={"code": 0, "data": [{"slug": "x"}]},
        request=httpx.Request("GET", "https://flomoapp.com/api/v1/memo/updated/")
    )

    responses = iter([
        httpx.TimeoutException("timed out"),
        success_response,
    ])
    call_count = {"n": 0}
    def fake_request(*args, **kwargs):
        call_count["n"] += 1
        r = next(responses)
        if isinstance(r, Exception):
            raise r
        return r

    with patch.object(client._client, "request", side_effect=fake_request):
        with patch("src.api.client.time.sleep"):
            data = client.get_updated(limit=1)

    assert call_count["n"] == 2
    assert data["code"] == 0


def test_rate_limit_5xx_retries():
    """502/503/504 should retry."""
    client = _make_client()

    success = httpx.Response(
        200, json={"code": 0, "data": []},
        request=httpx.Request("GET", "https://flomoapp.com/api/v1/memo/updated/")
    )
    error_503 = httpx.Response(
        503, text="unavailable",
        request=httpx.Request("GET", "https://flomoapp.com/api/v1/memo/updated/")
    )

    responses = iter([error_503, success])
    def fake_request(*args, **kwargs):
        r = next(responses)
        return r

    with patch.object(client._client, "request", side_effect=fake_request):
        with patch("src.api.client.time.sleep"):
            data = client.get_updated(limit=1)

    assert data["code"] == 0


def test_generic_api_error_raised():
    """Non-auth API errors (code != 0, != -10/-100) raise FlomoAPIError."""
    client = _make_client()
    resp = httpx.Response(
        200, json={"code": -5, "message": "some other error"},
        request=httpx.Request("GET", "https://flomoapp.com/api/v1/memo/updated/")
    )

    with patch.object(client._client, "request", return_value=resp):
        with pytest.raises(FlomoAPIError) as exc_info:
            client.get_updated(limit=1)

    # Should be FlomoAPIError but NOT FlomoAuthError
    assert not isinstance(exc_info.value, FlomoAuthError)


def test_verify_returns_false_on_auth_error():
    """verify() catches errors and returns False instead of raising."""
    client = _make_client()
    resp = httpx.Response(
        200, json={"code": -10, "message": "请先登录"},
        request=httpx.Request("GET", "https://flomoapp.com/api/v1/memo/updated/")
    )
    with patch.object(client._client, "request", return_value=resp):
        assert client.verify() is False


def test_verify_returns_true_on_success():
    client = _make_client()
    resp = httpx.Response(
        200, json={"code": 0, "data": []},
        request=httpx.Request("GET", "https://flomoapp.com/api/v1/memo/updated/")
    )
    with patch.object(client._client, "request", return_value=resp):
        assert client.verify() is True
