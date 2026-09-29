"""End-to-end API behaviour, with the provider replaced by a test double."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.generation.base import ProviderTimeoutError, ProviderUnavailableError
from tests.conftest import FakeProvider, build_client, make_glb

# --- happy path -------------------------------------------------------------


def test_valid_prompt_returns_model(client, fake_provider):
    r = client.post("/api/generate", json={"prompt": "A futuristic cyberpunk helmet"})
    assert r.status_code == 200
    body = r.json()

    assert body["success"] is True
    assert body["format"] == "glb"
    assert body["model_url"].startswith("/api/models/")
    assert body["model_url"].endswith(".glb")
    assert body["filename"] == "formly-futuristic-cyberpunk-helmet.glb"
    assert body["vertex_count"] == 300
    assert body["provider"] == "fake"
    # Latency is measured, not invented.
    assert body["generation_seconds"] == 1.23
    assert fake_provider.calls == ["A futuristic cyberpunk helmet"]


def test_prompt_is_normalised_before_reaching_provider(client, fake_provider):
    client.post("/api/generate", json={"prompt": "  A   small   pagoda \n"})
    assert fake_provider.calls == ["A small pagoda"]


def test_generated_model_is_fetchable_and_downloadable(client):
    body = client.post("/api/generate", json={"prompt": "A treasure chest"}).json()

    render = client.get(body["model_url"])
    assert render.status_code == 200
    assert render.headers["content-type"] == "model/gltf-binary"
    assert render.content[:4] == b"glTF"
    assert "inline" in render.headers["content-disposition"]

    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert "formly-treasure-chest.glb" in download.headers["content-disposition"]
    assert download.content == render.content


# --- input validation -------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    ["", "   ", "\n\t "],
    ids=["empty", "spaces", "whitespace"],
)
def test_empty_prompt_rejected(client, prompt):
    r = client.post("/api/generate", json={"prompt": prompt})
    assert r.status_code == 422
    assert r.json()["success"] is False
    assert "describe" in r.json()["error"].lower()


def test_excessively_long_prompt_rejected(client):
    r = client.post("/api/generate", json={"prompt": "helmet " * 200})
    assert r.status_code == 422
    assert "300 characters" in r.json()["error"]


def test_missing_prompt_field_rejected(client):
    r = client.post("/api/generate", json={})
    assert r.status_code == 422
    assert r.json()["success"] is False


def test_prompt_with_unsupported_characters_rejected(client):
    r = client.post("/api/generate", json={"prompt": "a helmet <script>"})
    assert r.status_code == 422
    assert "unsupported characters" in r.json()["error"]


def test_invalid_prompt_never_calls_provider(client, fake_provider):
    client.post("/api/generate", json={"prompt": ""})
    assert fake_provider.calls == []


# --- provider failures ------------------------------------------------------


def test_provider_unavailable_returns_502(settings: Settings):
    provider = FakeProvider(error=ProviderUnavailableError("space is asleep"))
    c = build_client(provider, settings)
    try:
        r = c.post("/api/generate", json={"prompt": "A helmet"})
        assert r.status_code == 502
        assert r.json() == {"success": False, "error": "The generation service is unavailable"}
        # The internal detail must not leak to the client.
        assert "asleep" not in r.text
    finally:
        c.__exit__(None, None, None)


def test_provider_timeout_returns_502_with_its_own_message(settings: Settings):
    provider = FakeProvider(error=ProviderTimeoutError("timed out after 300s"))
    c = build_client(provider, settings)
    try:
        r = c.post("/api/generate", json={"prompt": "A helmet"})
        assert r.status_code == 502
        assert r.json()["error"] == "Generation took too long"
    finally:
        c.__exit__(None, None, None)


def test_unexpected_provider_crash_returns_500(settings: Settings):
    provider = FakeProvider(error=RuntimeError("boom: secret-token-abc"))
    c = build_client(provider, settings)
    try:
        r = c.post("/api/generate", json={"prompt": "A helmet"})
        assert r.status_code == 500
        assert r.json()["success"] is False
        assert "secret-token-abc" not in r.text
    finally:
        c.__exit__(None, None, None)


# --- asset validation failures ----------------------------------------------


@pytest.mark.parametrize(
    "payload,label",
    [
        (b"<!DOCTYPE html><html>502 Bad Gateway</html>" * 40, "html_error_page"),
        (b"", "empty_asset"),
        (make_glb()[:200], "truncated_glb"),
        (make_glb(with_meshes=False), "no_meshes"),
    ],
)
def test_invalid_provider_response_fails_closed(settings: Settings, payload: bytes, label: str):
    """A bad asset must become a controlled error, never a fake success."""
    provider = FakeProvider(payload=payload)
    c = build_client(provider, settings)
    try:
        r = c.post("/api/generate", json={"prompt": "A helmet"})
        assert r.status_code == 502, label
        assert r.json() == {
            "success": False,
            "error": "The generated model could not be loaded",
        }
    finally:
        c.__exit__(None, None, None)


# --- asset serving ----------------------------------------------------------


def test_unknown_asset_returns_404(client):
    r = client.get("/api/models/deadbeef.glb")
    assert r.status_code == 404
    assert r.json()["success"] is False


def test_unknown_asset_download_returns_404(client):
    r = client.get("/api/models/deadbeef/download")
    assert r.status_code == 404


# --- rate limiting ----------------------------------------------------------


def test_rate_limit_returns_429_after_quota(settings: Settings):
    limited = settings.model_copy(update={"rate_limit_requests": 2})
    c = build_client(FakeProvider(), limited)
    try:
        assert c.post("/api/generate", json={"prompt": "A helmet"}).status_code == 200
        assert c.post("/api/generate", json={"prompt": "A helmet"}).status_code == 200
        third = c.post("/api/generate", json={"prompt": "A helmet"})
        assert third.status_code == 429
        assert "Retry-After" in third.headers
    finally:
        c.__exit__(None, None, None)


# --- meta -------------------------------------------------------------------


def test_health_reports_provider(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["format"] == "glb"


def test_every_response_carries_a_request_id(client):
    r = client.post("/api/generate", json={"prompt": "A helmet"})
    assert r.headers.get("X-Request-ID")


def test_cors_allows_configured_origin_only(client):
    ok = client.options(
        "/api/generate",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"

    blocked = client.options(
        "/api/generate",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert blocked.headers.get("access-control-allow-origin") is None
