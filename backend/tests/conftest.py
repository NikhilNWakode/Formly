"""Shared test fixtures.

`make_glb` builds a real, structurally valid GLB in memory so the test suite
never needs the network or a committed binary fixture.
"""

from __future__ import annotations

import json
import struct

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.services.generation.base import (
    GeneratedAsset,
    GenerationProvider,
    ProviderUnavailableError,
)


def make_glb(*, vertex_count: int = 300, with_meshes: bool = True) -> bytes:
    """Build a minimal but valid glTF 2.0 binary file."""
    # A simple fan of vertices -- geometry content is irrelevant, structure is not.
    positions = b"".join(
        struct.pack("<fff", i * 0.01, (i % 7) * 0.01, (i % 3) * 0.01) for i in range(vertex_count)
    )
    while len(positions) % 4:
        positions += b"\x00"

    gltf: dict = {
        "asset": {"version": "2.0", "generator": "formly-tests"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,  # FLOAT
                "count": vertex_count,
                "type": "VEC3",
            }
        ],
    }
    if with_meshes:
        gltf["meshes"] = [{"primitives": [{"attributes": {"POSITION": 0}, "mode": 4}]}]

    json_chunk = json.dumps(gltf).encode("utf-8")
    while len(json_chunk) % 4:
        json_chunk += b" "  # spec: pad JSON chunk with spaces

    total = 12 + 8 + len(json_chunk) + 8 + len(positions)
    out = struct.pack("<4sII", b"glTF", 2, total)
    out += struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
    out += struct.pack("<I4s", len(positions), b"BIN\x00") + positions
    return out


class FakeProvider(GenerationProvider):
    """Test double standing in for the real Space.

    Used only in tests -- the application itself never serves a canned asset.
    """

    name = "fake"

    def __init__(self, *, payload: bytes | None = None, error: Exception | None = None):
        self.payload = payload if payload is not None else make_glb()
        self.error = error
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> GeneratedAsset:
        self.calls.append(prompt)
        if self.error:
            raise self.error
        return GeneratedAsset(
            data=self.payload, fmt="glb", provider=self.name, latency_seconds=1.23
        )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        cors_origins="http://localhost:3000",
        rate_limit_requests=1000,
        rate_limit_window_seconds=60,
    )


def build_client(provider: GenerationProvider, settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    # Enter the lifespan so app.state is populated, then swap in the double.
    client.__enter__()
    app.state.provider = provider
    from app.services.rate_limit import RateLimiter

    app.state.limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    return client


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(fake_provider: FakeProvider, settings: Settings):
    c = build_client(fake_provider, settings)
    yield c
    c.__exit__(None, None, None)
