"""Structural validation of GLB assets returned by a provider.

We never trust provider output. A truncated download, an HTML error page saved
with a .glb extension, or a mesh with no geometry would all "look" like success
to a naive size check but fail in the browser. Validating here converts a
confusing client-side crash into a controlled API error.

This is a structural sanity check against the glTF 2.0 binary container spec,
not a full glTF conformance validator -- that would be a large dependency for
little extra signal in this system.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

GLB_MAGIC = b"glTF"
GLB_HEADER_SIZE = 12
CHUNK_HEADER_SIZE = 8
CHUNK_TYPE_JSON = b"JSON"
CHUNK_TYPE_BIN = b"BIN\x00"


@dataclass(frozen=True)
class GlbInfo:
    """Facts extracted from a GLB during validation, useful for logging."""

    byte_size: int
    mesh_count: int
    vertex_count: int
    triangle_count: int
    has_normals: bool
    has_vertex_colors: bool
    material_count: int


class AssetValidationError(Exception):
    """Raised when provider output is not a usable GLB."""


def validate_glb(data: bytes, *, min_bytes: int = 1024, max_bytes: int | None = None) -> GlbInfo:
    """Validate `data` as a glTF 2.0 binary (GLB) file.

    Returns extracted `GlbInfo` on success, raises `AssetValidationError`
    otherwise.
    """
    if not data:
        raise AssetValidationError("asset is empty")

    if len(data) < min_bytes:
        raise AssetValidationError(
            f"asset too small to be a real model ({len(data)} bytes < {min_bytes})"
        )

    if max_bytes is not None and len(data) > max_bytes:
        raise AssetValidationError(f"asset too large ({len(data)} bytes > {max_bytes})")

    if len(data) < GLB_HEADER_SIZE:
        raise AssetValidationError("asset shorter than a GLB header")

    magic, version, declared_length = struct.unpack_from("<4sII", data, 0)

    if magic != GLB_MAGIC:
        # Most common real-world cause: an HTML error page or JSON error body.
        raise AssetValidationError(f"not a GLB file (magic was {magic!r})")

    if version != 2:
        raise AssetValidationError(f"unsupported GLB version {version}, expected 2")

    if declared_length != len(data):
        # Almost always a truncated or padded download.
        raise AssetValidationError(
            f"GLB length mismatch: header declares {declared_length}, got {len(data)}"
        )

    gltf: dict | None = None
    saw_bin = False
    offset = GLB_HEADER_SIZE

    while offset + CHUNK_HEADER_SIZE <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += CHUNK_HEADER_SIZE

        if offset + chunk_length > len(data):
            raise AssetValidationError("GLB chunk extends past end of file")

        chunk = data[offset : offset + chunk_length]
        offset += chunk_length

        if chunk_type == CHUNK_TYPE_JSON and gltf is None:
            try:
                gltf = json.loads(chunk.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AssetValidationError(f"GLB JSON chunk is not valid JSON: {exc}") from exc
        elif chunk_type == CHUNK_TYPE_BIN:
            saw_bin = True

    if gltf is None:
        raise AssetValidationError("GLB has no JSON chunk")

    if not isinstance(gltf, dict):
        raise AssetValidationError("GLB JSON chunk is not an object")

    asset_version = str(gltf.get("asset", {}).get("version", ""))
    if not asset_version.startswith("2."):
        raise AssetValidationError(f"unsupported glTF asset version {asset_version!r}")

    meshes = gltf.get("meshes") or []
    if not meshes:
        raise AssetValidationError("GLB contains no meshes")

    accessors = gltf.get("accessors") or []

    vertex_count = 0
    triangle_count = 0
    has_normals = False
    has_vertex_colors = False
    renderable_primitives = 0

    def accessor_count(index: object) -> int:
        if isinstance(index, int) and 0 <= index < len(accessors):
            count = accessors[index].get("count")
            return count if isinstance(count, int) else 0
        return 0

    for mesh in meshes:
        for primitive in mesh.get("primitives") or []:
            attributes = primitive.get("attributes") or {}
            if "POSITION" not in attributes:
                # A primitive with no positions cannot be drawn.
                continue

            renderable_primitives += 1
            vertex_count += accessor_count(attributes["POSITION"])
            has_normals = has_normals or "NORMAL" in attributes
            has_vertex_colors = has_vertex_colors or "COLOR_0" in attributes

            # mode 4 == TRIANGLES, the glTF default.
            if primitive.get("mode", 4) == 4:
                if "indices" in primitive:
                    triangle_count += accessor_count(primitive["indices"]) // 3
                else:
                    triangle_count += accessor_count(attributes["POSITION"]) // 3

    if renderable_primitives == 0:
        raise AssetValidationError("GLB has meshes but no primitive with POSITION data")

    if vertex_count == 0:
        raise AssetValidationError("GLB geometry contains zero vertices")

    if not saw_bin and not gltf.get("buffers"):
        raise AssetValidationError("GLB has geometry but no buffer data")

    return GlbInfo(
        byte_size=len(data),
        mesh_count=len(meshes),
        vertex_count=vertex_count,
        triangle_count=triangle_count,
        has_normals=has_normals,
        has_vertex_colors=has_vertex_colors,
        material_count=len(gltf.get("materials") or []),
    )
