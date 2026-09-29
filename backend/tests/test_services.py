"""Unit tests for the supporting services."""

from __future__ import annotations

import time

import pytest

from app.services.generation.base import ProviderTimeoutError, ProviderUnavailableError
from app.services.generation.shap_e import ShapEProvider
from app.services.naming import build_filename, slugify_prompt
from app.services.rate_limit import RateLimiter
from app.services.store import AssetStore
from tests.conftest import make_glb

# --- filenames --------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("A futuristic cyberpunk helmet", "formly-futuristic-cyberpunk-helmet.glb"),
        ("A low-poly medieval treasure chest", "formly-low-poly-medieval-treasure-chest.glb"),
        ("The Japanese pagoda", "formly-japanese-pagoda.glb"),
        ("  spaced   out  ", "formly-spaced-out.glb"),
    ],
)
def test_build_filename(prompt, expected):
    assert build_filename(prompt) == expected


@pytest.mark.parametrize(
    "hostile",
    [
        "../../etc/passwd",
        "a/b/c",
        'name"; rm -rf /',
        "..\\..\\windows\\system32",
        "\u0000null",
        "!!!",
        "",
    ],
)
def test_slugify_is_always_filesystem_safe(hostile):
    """A prompt must never be able to steer the download path."""
    slug = slugify_prompt(hostile)
    assert slug
    assert all(c.islower() or c.isdigit() or c == "-" for c in slug), slug
    assert ".." not in slug
    assert "/" not in slug and "\\" not in slug


def test_slug_length_is_bounded():
    assert len(slugify_prompt("word " * 100)) <= 48


# --- asset store ------------------------------------------------------------


def test_store_roundtrip():
    store = AssetStore(ttl_seconds=60, max_items=4)
    try:
        data = make_glb()
        store.put("abc", data, filename="formly-x.glb", media_type="model/gltf-binary")
        got = store.get("abc")
        assert got is not None
        assert got.path.read_bytes() == data
        assert got.byte_size == len(data)
    finally:
        store.clear()


def test_store_returns_none_for_unknown_id():
    store = AssetStore()
    try:
        assert store.get("missing") is None
    finally:
        store.clear()


def test_store_expires_assets():
    store = AssetStore(ttl_seconds=0, max_items=4)
    try:
        store.put("abc", make_glb(), filename="f.glb", media_type="model/gltf-binary")
        time.sleep(0.01)
        assert store.get("abc") is None
    finally:
        store.clear()


def test_store_evicts_oldest_past_capacity():
    store = AssetStore(ttl_seconds=600, max_items=2)
    try:
        for i in range(4):
            store.put(f"a{i}", make_glb(), filename="f.glb", media_type="model/gltf-binary")
            time.sleep(0.01)  # keep created_at ordering distinct
        assert store.get("a0") is None
        assert store.get("a1") is None
        assert store.get("a3") is not None
    finally:
        store.clear()


def test_store_clear_removes_files_from_disk():
    store = AssetStore()
    store.put("abc", make_glb(), filename="f.glb", media_type="model/gltf-binary")
    path = store.get("abc").path
    assert path.exists()
    store.clear()
    assert not path.exists()


def test_store_handles_file_deleted_behind_its_back():
    store = AssetStore()
    try:
        store.put("abc", make_glb(), filename="f.glb", media_type="model/gltf-binary")
        store.get("abc").path.unlink()
        assert store.get("abc") is None
    finally:
        store.clear()


# --- rate limiter -----------------------------------------------------------


def test_rate_limiter_allows_then_blocks():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is False
    assert limiter.retry_after("ip") > 0


def test_rate_limiter_is_per_key():
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True


def test_rate_limiter_window_rolls_over():
    limiter = RateLimiter(max_requests=1, window_seconds=0)
    assert limiter.allow("ip") is True
    time.sleep(0.01)
    assert limiter.allow("ip") is True


# --- provider retry behaviour ----------------------------------------------
#
# These exercise the retry loop against a stubbed gradio call, so they cover the
# cold-start 502 behaviour observed against the real Space without the network.


def _provider(**kwargs) -> ShapEProvider:
    defaults = dict(max_attempts=3, backoff_seconds=0.0, timeout_seconds=5.0)
    defaults.update(kwargs)
    return ShapEProvider(**defaults)


async def test_provider_retries_transient_failure_then_succeeds(monkeypatch):
    provider = _provider()
    calls = {"n": 0}
    payload = make_glb()

    async def fake_get_client():
        return object()

    def fake_predict(client, prompt):
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("502 Bad Gateway from upstream")
        return payload

    monkeypatch.setattr(provider, "_get_client", fake_get_client)
    monkeypatch.setattr(provider, "_predict_sync", fake_predict)

    asset = await provider.generate("a helmet")
    assert asset.data == payload
    assert asset.provider == "shap-e"
    assert calls["n"] == 3


async def test_provider_gives_up_after_max_attempts(monkeypatch):
    provider = _provider(max_attempts=2)
    calls = {"n": 0}

    async def fake_get_client():
        return object()

    def fake_predict(client, prompt):
        calls["n"] += 1
        raise Exception("502 Bad Gateway")

    monkeypatch.setattr(provider, "_get_client", fake_get_client)
    monkeypatch.setattr(provider, "_predict_sync", fake_predict)

    with pytest.raises(ProviderUnavailableError):
        await provider.generate("a helmet")
    assert calls["n"] == 2


async def test_provider_does_not_retry_quota_errors(monkeypatch):
    """Retrying an exhausted GPU quota only wastes the user's time."""
    provider = _provider(max_attempts=3)
    calls = {"n": 0}

    async def fake_get_client():
        return object()

    def fake_predict(client, prompt):
        calls["n"] += 1
        raise Exception("You have exceeded your GPU quota")

    monkeypatch.setattr(provider, "_get_client", fake_get_client)
    monkeypatch.setattr(provider, "_predict_sync", fake_predict)

    with pytest.raises(ProviderUnavailableError, match="quota"):
        await provider.generate("a helmet")
    assert calls["n"] == 1


async def test_provider_timeout_is_not_retried(monkeypatch):
    provider = _provider(max_attempts=3, timeout_seconds=0.05)
    calls = {"n": 0}

    async def fake_get_client():
        return object()

    def fake_predict(client, prompt):
        calls["n"] += 1
        time.sleep(0.5)
        return make_glb()

    monkeypatch.setattr(provider, "_get_client", fake_get_client)
    monkeypatch.setattr(provider, "_predict_sync", fake_predict)

    with pytest.raises(ProviderTimeoutError):
        await provider.generate("a helmet")
    assert calls["n"] == 1


# --- provider/client contract ----------------------------------------------


def test_client_accepts_the_token_kwarg_we_pass():
    """Guard the gradio_client `hf_token` -> `token` rename.

    The authenticated path only runs when HF_TOKEN is configured, so a rename
    here fails invisibly during anonymous development and only surfaces in
    production. This asserts the kwarg the provider actually passes exists.
    """
    import inspect

    from gradio_client import Client

    params = inspect.signature(Client.__init__).parameters
    assert "token" in params, (
        "gradio_client.Client no longer accepts `token`; "
        "update ShapEProvider._build_client_sync"
    )


async def test_provider_does_not_retry_signature_errors(monkeypatch):
    provider = _provider(max_attempts=3)
    calls = {"n": 0}

    async def fake_get_client():
        return object()

    def fake_predict(client, prompt):
        calls["n"] += 1
        raise TypeError("Client.__init__() got an unexpected keyword argument 'hf_token'")

    monkeypatch.setattr(provider, "_get_client", fake_get_client)
    monkeypatch.setattr(provider, "_predict_sync", fake_predict)

    with pytest.raises(ProviderUnavailableError):
        await provider.generate("a helmet")
    assert calls["n"] == 1
