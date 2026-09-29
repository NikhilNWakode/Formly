"""Asset validation: the guard between a flaky provider and the browser."""

from __future__ import annotations

import json
import struct

import pytest

from app.services.generation.validator import AssetValidationError, validate_glb
from tests.conftest import make_glb


def test_accepts_valid_glb():
    info = validate_glb(make_glb(vertex_count=300))
    assert info.vertex_count == 300
    assert info.triangle_count == 100
    assert info.mesh_count == 1


def test_rejects_empty_asset():
    with pytest.raises(AssetValidationError, match="empty"):
        validate_glb(b"")


def test_rejects_html_error_page():
    """The realistic failure: a sleeping Space returns a 502 HTML page."""
    page = b"<!DOCTYPE html><html><body>502 Bad Gateway</body></html>" * 40
    with pytest.raises(AssetValidationError, match="not a GLB"):
        validate_glb(page)


def test_rejects_json_error_body():
    body = b'{"error":"quota exceeded"}' * 100
    with pytest.raises(AssetValidationError, match="not a GLB"):
        validate_glb(body)


def test_rejects_truncated_file():
    full = make_glb()
    with pytest.raises(AssetValidationError, match="length mismatch"):
        validate_glb(full[: len(full) // 2])


def test_rejects_too_small_asset():
    with pytest.raises(AssetValidationError, match="too small"):
        validate_glb(b"glTF" + b"\x00" * 40, min_bytes=1024)


def test_rejects_oversized_asset():
    with pytest.raises(AssetValidationError, match="too large"):
        validate_glb(make_glb(), min_bytes=10, max_bytes=100)


def test_rejects_wrong_version():
    data = bytearray(make_glb())
    struct.pack_into("<I", data, 4, 3)  # version field -> 3
    with pytest.raises(AssetValidationError, match="unsupported GLB version"):
        validate_glb(bytes(data))


def test_rejects_glb_without_meshes():
    with pytest.raises(AssetValidationError, match="no meshes"):
        validate_glb(make_glb(with_meshes=False))


def test_rejects_mesh_without_position():
    """A mesh that exists but cannot be drawn must not pass."""
    gltf = {
        "asset": {"version": "2.0"},
        "meshes": [{"primitives": [{"attributes": {"NORMAL": 0}}]}],
        "accessors": [{"componentType": 5126, "count": 3, "type": "VEC3"}],
    }
    chunk = json.dumps(gltf).encode()
    while len(chunk) % 4:
        chunk += b" "
    blob = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(chunk))
    blob += struct.pack("<I4s", len(chunk), b"JSON") + chunk
    with pytest.raises(AssetValidationError, match="no primitive with POSITION"):
        validate_glb(blob, min_bytes=10)


def test_reports_vertex_colors_and_missing_normals():
    """Shap-E output has COLOR_0 but no NORMAL -- the viewer depends on this."""
    gltf = {
        "asset": {"version": "2.0"},
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 0}, "mode": 4}]}],
        "accessors": [{"componentType": 5126, "count": 30, "type": "VEC3"}],
        "buffers": [{"byteLength": 4}],
    }
    chunk = json.dumps(gltf).encode()
    while len(chunk) % 4:
        chunk += b" "
    blob = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(chunk))
    blob += struct.pack("<I4s", len(chunk), b"JSON") + chunk
    info = validate_glb(blob, min_bytes=10)
    assert info.has_vertex_colors is True
    assert info.has_normals is False
    assert info.material_count == 0
