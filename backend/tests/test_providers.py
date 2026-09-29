"""Provider-level tests for the Space-backed generators.

External inference is always mocked here: the suite must never depend on a live
GPU Space, which is both slow and subject to a shared quota. The one test that
touches the network is marked `live` and skipped unless FORMLY_LIVE_TESTS=1.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import anyio
import pytest

from app.config import Settings
from app.services.generation.base import ProviderTimeoutError, ProviderUnavailableError
from app.services.generation.hf_space import FailureKind, classify, is_retryable, result_path
from app.services.generation.registry import AVAILABLE_PROVIDERS, build_provider
from app.services.generation.shap_e import ShapEProvider
from app.services.generation.trellis import TrellisProvider
from tests.conftest import make_glb

# --- failure classification -------------------------------------------------
#
# The strings below are verbatim messages observed from the real Spaces during
# provider evaluation, which is what makes these assertions meaningful.


@pytest.mark.parametrize(
    "message,expected",
    [
        (
            "You have exceeded your ZeroGPU runs limit. Subscribe to Hugging Face PRO",
            FailureKind.QUOTA,
        ),
        (
            "You have exceeded your ZeroGPU quota (60s requested vs. 0s left)",
            FailureKind.QUOTA,
        ),
        (
            "Server error '502 Bad Gateway' for url 'https://x.hf.space/gradio_api/queue/join'",
            FailureKind.TRANSIENT,
        ),
        ("Could not fetch config for https://x.hf.space", FailureKind.TRANSIENT),
        ("Could not fetch api info for https://x.hf.space", FailureKind.TRANSIENT),
        (
            "Text to 3D is disable. Please enable it by `python gradio_app.py --enable_t23d`.",
            FailureKind.REFUSED,
        ),
        ("ValueError: could not decode the payload", FailureKind.UNKNOWN),
    ],
)
def test_classify_real_provider_messages(message: str, expected: FailureKind):
    assert classify(Exception(message)) is expected


def test_only_transient_and_unknown_are_retried():
    assert is_retryable(FailureKind.TRANSIENT)
    assert is_retryable(FailureKind.UNKNOWN)
    # Retrying these wastes the user's time and a shared GPU quota.
    assert not is_retryable(FailureKind.QUOTA)
    assert not is_retryable(FailureKind.REFUSED)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("/tmp/a.glb", "/tmp/a.glb"),
        ({"path": "/tmp/b.glb"}, "/tmp/b.glb"),
        ({"url": "/tmp/c.glb"}, "/tmp/c.glb"),
        ([{"path": "/tmp/d.glb"}], "/tmp/d.glb"),
        ((None, {"path": "/tmp/e.glb"}), "/tmp/e.glb"),
        ("", None),
        ({}, None),
        (None, None),
    ],
)
def test_result_path_handles_gradio_return_shapes(value, expected):
    assert result_path(value) == expected


# --- registry / configuration ----------------------------------------------


def test_registry_builds_every_advertised_provider():
    for name in AVAILABLE_PROVIDERS:
        provider = build_provider(Settings(provider=name))
        assert provider.name == name


def test_registry_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown generation provider"):
        build_provider(Settings(provider="does-not-exist"))


def test_default_provider_is_shap_e():
    """Shap-E stays the default; TRELLIS is opt-in. See README evaluation."""
    assert Settings().provider == "shap-e"
    assert build_provider(Settings()).name == "shap-e"


def test_trellis_is_configurable_from_environment():
    settings = Settings(
        provider="trellis",
        trellis_space="someone/Other-TRELLIS",
        trellis_resolution="512",
        trellis_max_attempts=1,
    )
    provider = build_provider(settings)
    assert isinstance(provider, TrellisProvider)
    assert provider._space == "someone/Other-TRELLIS"
    assert provider._resolution == "512"
    assert provider._max_attempts == 1


def test_trellis_retries_fewer_times_than_shap_e_by_default():
    """One TRELLIS attempt costs ~4x the GPU quota, so it retries less."""
    assert Settings().trellis_max_attempts < Settings().provider_max_attempts


# --- TRELLIS pipeline behaviour --------------------------------------------


class FakeGradioClient:
    """Stands in for `gradio_client.Client` across the three-stage pipeline."""

    def __init__(self, tmp_path: Path, *, glb_bytes: bytes | None = None, fail_on=None,
                 raises: Exception | None = None, glb_name: str = "out.glb",
                 gen3d_result=None):
        self.tmp_path = tmp_path
        self.calls: list[str] = []
        self.fail_on = fail_on
        self.raises = raises
        self.gen3d_result = gen3d_result

        self.image = tmp_path / "img.png"
        self.image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        self.clean = tmp_path / "clean.png"
        self.clean.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 64)
        self.glb = tmp_path / glb_name
        self.glb.write_bytes(glb_bytes if glb_bytes is not None else make_glb())

    def predict(self, *args, api_name: str, **kwargs):
        self.calls.append(api_name)
        if self.fail_on == api_name and self.raises:
            raise self.raises
        if api_name == "/start_session":
            return None
        if api_name == "/generate_txt2img":
            return str(self.image)
        if api_name == "/preprocess_image":
            return str(self.clean)
        if api_name == "/generate_3d":
            if self.gen3d_result is not None:
                return self.gen3d_result
            # Real shape: a viewer payload plus the GLB download.
            return ["<rerun viewer payload>", {"path": str(self.glb)}]
        raise AssertionError(f"unexpected endpoint {api_name}")


def _trellis(monkeypatch, client: FakeGradioClient, **kwargs) -> TrellisProvider:
    provider = TrellisProvider(max_attempts=kwargs.pop("max_attempts", 1),
                               backoff_seconds=0.0, timeout_seconds=kwargs.pop("timeout", 10.0),
                               **kwargs)
    monkeypatch.setattr(provider, "_build_client_sync", lambda: client)
    return provider


async def test_trellis_runs_the_full_pipeline_and_returns_glb(monkeypatch, tmp_path):
    payload = make_glb(vertex_count=200)
    client = FakeGradioClient(tmp_path, glb_bytes=payload)
    provider = _trellis(monkeypatch, client)

    asset = await provider.generate("a tiger")

    assert asset.data == payload
    assert asset.fmt == "glb"
    assert asset.provider == "trellis"
    assert asset.latency_seconds > 0
    # The three stages must run in order.
    assert client.calls == [
        "/start_session",
        "/generate_txt2img",
        "/preprocess_image",
        "/generate_3d",
    ]


async def test_trellis_survives_missing_start_session(monkeypatch, tmp_path):
    """A Space without session state must still work."""
    client = FakeGradioClient(
        tmp_path, fail_on="/start_session", raises=Exception("no such endpoint")
    )
    provider = _trellis(monkeypatch, client)
    asset = await provider.generate("a tiger")
    assert asset.data[:4] == b"glTF"


async def test_trellis_picks_the_glb_not_the_viewer_payload(monkeypatch, tmp_path):
    """generate_3d returns a viewer payload alongside the file."""
    client = FakeGradioClient(tmp_path)
    client.gen3d_result = [
        {"path": str(tmp_path / "preview.mp4")},
        {"path": str(client.glb)},
    ]
    (tmp_path / "preview.mp4").write_bytes(b"not a model")
    provider = _trellis(monkeypatch, client)

    asset = await provider.generate("a tiger")
    assert asset.data[:4] == b"glTF"


async def test_trellis_fails_when_no_glb_returned(monkeypatch, tmp_path):
    client = FakeGradioClient(tmp_path)
    client.gen3d_result = ["<viewer only>"]
    provider = _trellis(monkeypatch, client)

    with pytest.raises(ProviderUnavailableError, match="no GLB"):
        await provider.generate("a tiger")


async def test_trellis_fails_when_txt2img_returns_nothing(monkeypatch, tmp_path):
    client = FakeGradioClient(tmp_path)
    monkeypatch.setattr(client, "predict", lambda *a, api_name, **k: None)
    provider = _trellis(monkeypatch, client)

    with pytest.raises(ProviderUnavailableError, match="no image"):
        await provider.generate("a tiger")


async def test_trellis_does_not_retry_quota(monkeypatch, tmp_path):
    client = FakeGradioClient(
        tmp_path,
        fail_on="/generate_txt2img",
        raises=Exception("You have exceeded your ZeroGPU runs limit"),
    )
    provider = _trellis(monkeypatch, client, max_attempts=3)

    with pytest.raises(ProviderUnavailableError, match="quota"):
        await provider.generate("a tiger")
    assert client.calls.count("/generate_txt2img") == 1


async def test_trellis_does_not_retry_refused_feature(monkeypatch, tmp_path):
    client = FakeGradioClient(
        tmp_path, fail_on="/generate_3d", raises=Exception("Text to 3D is disable.")
    )
    provider = _trellis(monkeypatch, client, max_attempts=3)

    with pytest.raises(ProviderUnavailableError, match="refused"):
        await provider.generate("a tiger")
    assert client.calls.count("/generate_3d") == 1


async def test_trellis_retries_transient_then_succeeds(monkeypatch, tmp_path):
    payload = make_glb()
    attempts = {"n": 0}

    class Flaky(FakeGradioClient):
        def predict(self, *args, api_name: str, **kwargs):
            if api_name == "/generate_txt2img":
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise Exception("Server error '502 Bad Gateway' for url")
            return super().predict(*args, api_name=api_name, **kwargs)

    client = Flaky(tmp_path, glb_bytes=payload)
    provider = _trellis(monkeypatch, client, max_attempts=2)

    asset = await provider.generate("a tiger")
    assert asset.data == payload
    assert attempts["n"] == 2


async def test_trellis_timeout_is_not_retried(monkeypatch, tmp_path):
    class Slow(FakeGradioClient):
        def predict(self, *args, api_name: str, **kwargs):
            if api_name == "/generate_3d":
                time.sleep(0.6)
            return super().predict(*args, api_name=api_name, **kwargs)

    client = Slow(tmp_path)
    provider = _trellis(monkeypatch, client, max_attempts=3, timeout=0.1)

    with pytest.raises(ProviderTimeoutError):
        await provider.generate("a tiger")

    # The timed-out worker thread is abandoned by design (abandon_on_cancel),
    # so it keeps running and still logs. Let it finish inside the test rather
    # than writing to pytest's captured stream after teardown.
    await anyio.sleep(0.8)


async def test_trellis_signature_error_is_not_retried(monkeypatch, tmp_path):
    client = FakeGradioClient(
        tmp_path,
        fail_on="/generate_3d",
        raises=TypeError("predict() got an unexpected keyword argument 'resolution'"),
    )
    provider = _trellis(monkeypatch, client, max_attempts=3)

    with pytest.raises(ProviderUnavailableError, match="called incorrectly"):
        await provider.generate("a tiger")
    assert client.calls.count("/generate_3d") == 1


async def test_trellis_invalid_asset_reaches_the_validator(monkeypatch, tmp_path, settings):
    """A non-GLB payload must fail closed at the API, not render as a model."""
    from tests.conftest import FakeProvider, build_client

    client = FakeGradioClient(tmp_path, glb_bytes=b"<!DOCTYPE html>502" * 80)
    provider = _trellis(monkeypatch, client)
    asset = await provider.generate("a tiger")
    assert asset.data[:4] != b"glTF"  # provider itself does not validate

    api = build_client(FakeProvider(payload=asset.data), settings)
    try:
        r = api.post("/api/generate", json={"prompt": "a tiger"})
        assert r.status_code == 502
        assert r.json() == {
            "success": False,
            "error": "The generated model could not be loaded",
        }
    finally:
        api.__exit__(None, None, None)


# --- API compatibility ------------------------------------------------------


def test_api_contract_is_identical_across_providers(settings):
    """Swapping providers must not change the frontend-facing response."""
    from tests.conftest import FakeProvider, build_client

    class TrellisShaped(FakeProvider):
        name = "trellis"

    api = build_client(TrellisShaped(), settings)
    try:
        body = api.post("/api/generate", json={"prompt": "a tiger"}).json()
        assert body["success"] is True
        assert body["format"] == "glb"
        assert body["model_url"].endswith(".glb")
        assert body["provider"] == "trellis"
        # Exactly the keys the frontend reads today.
        assert {"model_url", "download_url", "filename", "format"} <= set(body)
    finally:
        api.__exit__(None, None, None)


# --- provider construction --------------------------------------------------


def test_providers_accept_a_token_without_leaking_it():
    for provider in (
        ShapEProvider(hf_token="hf_secret_value"),
        TrellisProvider(hf_token="hf_secret_value"),
    ):
        assert "hf_secret_value" not in repr(provider)


# --- live contract check (opt-in) ------------------------------------------


@pytest.mark.skipif(
    os.environ.get("FORMLY_LIVE_TESTS") != "1",
    reason="live Space schema check; set FORMLY_LIVE_TESTS=1 to run",
)
def test_live_trellis_space_still_exposes_expected_endpoints():
    """Guard the TRELLIS Space's API contract without spending GPU quota.

    Reading `/gradio_api/info` is free; only `predict` consumes ZeroGPU time.
    This is the cheapest way to catch a Space renaming or removing a stage,
    which is exactly the class of break that a signature change caused before.
    """
    import json
    import urllib.request

    settings = Settings()
    host = settings.trellis_space.replace("/", "-").replace(".", "-").lower()
    info = json.load(
        urllib.request.urlopen(f"https://{host}.hf.space/gradio_api/info", timeout=45)
    )
    endpoints = info.get("named_endpoints", {})
    for required in ("/generate_txt2img", "/preprocess_image", "/generate_3d"):
        assert required in endpoints, f"{required} missing from {settings.trellis_space}"


def test_health_reports_the_active_providers_space(settings):
    """Regression: health used to read settings.hf_space, so it reported the
    Shap-E Space even when another provider was active."""
    from tests.conftest import build_client

    provider = TrellisProvider(space="someone/Some-TRELLIS")
    api = build_client(provider, settings)
    try:
        body = api.get("/api/health").json()
        assert body["provider"]["name"] == "trellis"
        assert body["provider"]["space"] == "someone/Some-TRELLIS"
    finally:
        api.__exit__(None, None, None)


def test_health_does_not_imply_the_upstream_space_is_healthy(client):
    """The Space flaps while reporting itself running, so a 200 here must not
    be readable as "generation works right now"."""
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    # Scope is stated explicitly rather than left for the reader to assume.
    assert body["scope"] == "api-only"
    assert body["provider"]["upstream_health"] == "not_checked"


def test_health_never_probes_the_provider(settings):
    """Health must not wake a sleeping GPU Space -- that would burn quota on
    every platform health check."""
    from tests.conftest import FakeProvider, build_client

    provider = FakeProvider()
    api = build_client(provider, settings)
    try:
        for _ in range(5):
            assert api.get("/api/health").status_code == 200
        assert provider.calls == []
    finally:
        api.__exit__(None, None, None)


# --- provider is not user-selectable ---------------------------------------


def test_client_cannot_choose_the_provider(settings):
    """Model selection is server-side configuration, not a request parameter.

    TRELLIS is unverified, so a user must not be able to route themselves to
    it. Extra fields on the request body are ignored by the schema.
    """
    from tests.conftest import FakeProvider, build_client

    api = build_client(FakeProvider(), settings)
    try:
        body = api.post(
            "/api/generate",
            json={"prompt": "a tiger", "provider": "trellis", "model": "trellis"},
        ).json()
        # The configured provider answered, not the one the client asked for.
        assert body["provider"] == "fake"
    finally:
        api.__exit__(None, None, None)


def test_generate_request_schema_exposes_only_prompt():
    """Guard against a provider/model field creeping into the public API."""
    from app.schemas.generation import GenerateRequest

    assert set(GenerateRequest.model_fields) == {"prompt"}


# --- CORS origin matching ---------------------------------------------------


def test_cors_allows_origins_matching_the_configured_regex(monkeypatch):
    """Vercel mints a new subdomain per deployment, so exact lists break.

    The regex must cover the production alias and preview deployments of the
    same project, and nothing else.

    CORS is configured inside create_app() from the cached settings, so the
    environment has to be set before the app is built -- overriding the
    dependency afterwards is too late.
    """
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv(
        "CORS_ORIGIN_REGEX", r"https://frontend-lefw(-[a-z0-9-]+)?\.vercel\.app"
    )
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as api:
            allowed = [
                "https://frontend-lefw.vercel.app",
                "https://frontend-lefw-g64u0wbbt-nikhil-wakodes-projects.vercel.app",
                "http://localhost:3000",
            ]
            for origin in allowed:
                r = api.options(
                    "/api/generate",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                    },
                )
                assert r.headers.get("access-control-allow-origin") == origin, origin

            # Another project on the same platform must NOT be allowed.
            for origin in [
                "https://someone-elses-app.vercel.app",
                "https://evil.example.com",
            ]:
                r = api.options(
                    "/api/generate",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                    },
                )
                assert r.headers.get("access-control-allow-origin") is None, origin
    finally:
        get_settings.cache_clear()


def test_cors_regex_is_off_by_default():
    """Without explicit configuration only the exact list applies."""
    from app.config import Settings

    assert Settings().cors_origin_regex is None
