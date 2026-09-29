"""Validation of the shipped demo assets.

These GLBs are static frontend files, but they are validated here because this
repository already owns a real GLB validator and a test runner. Adding a second
test stack to the frontend just for file checks would be more machinery than
the job needs.

What this guards: the examples exist, are genuinely valid GLB (not truncated or
LFS pointers), stay within a sane size budget, and the TypeScript manifest and
the files on disk cannot drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.generation.validator import AssetValidationError, validate_glb

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "frontend" / "public" / "examples"
MANIFEST = REPO_ROOT / "frontend" / "lib" / "examples.ts"

# Examples are fetched on demand, not on page load, so this is generous -- it
# exists to catch someone dropping in a 100 MB mesh, not to micro-tune.
MAX_EXAMPLE_BYTES = 8 * 1024 * 1024


def parse_manifest() -> list[dict]:
    """Extract the example entries from the TypeScript manifest.

    A regex rather than a JS parser: the manifest is a flat literal, and the
    point is only to cross-check it against the files on disk.
    """
    source = MANIFEST.read_text(encoding="utf-8")
    entries = []
    for block in re.findall(r"\{\s*id:.*?\}", source, re.S):
        entry = {}
        for key in ("id", "label", "prompt", "file"):
            m = re.search(rf"{key}:\s*\"([^\"]+)\"", block)
            if m:
                entry[key] = m.group(1)
        for key in ("triangleCount", "byteSize"):
            m = re.search(rf"{key}:\s*(\d+)", block)
            if m:
                entry[key] = int(m.group(1))
        if entry:
            entries.append(entry)
    return entries


MANIFEST_ENTRIES = parse_manifest()


def test_manifest_is_parseable_and_not_empty():
    assert MANIFEST_ENTRIES, "no example entries found in lib/examples.ts"


def test_examples_directory_exists():
    assert EXAMPLES_DIR.is_dir(), f"missing demo assets directory: {EXAMPLES_DIR}"


def test_at_least_two_examples_ship():
    """Two is the minimum that lets a reviewer switch between examples."""
    assert len(MANIFEST_ENTRIES) >= 2


@pytest.mark.parametrize("entry", MANIFEST_ENTRIES, ids=lambda e: e["id"])
def test_example_file_exists(entry: dict):
    path = EXAMPLES_DIR / Path(entry["file"]).name
    assert path.is_file(), f"{entry['id']}: missing file {path}"


@pytest.mark.parametrize("entry", MANIFEST_ENTRIES, ids=lambda e: e["id"])
def test_example_is_a_valid_glb(entry: dict):
    """The same validator the API applies to provider output.

    A truncated asset or a git-lfs pointer committed by mistake would fail
    here rather than in a reviewer's browser.
    """
    path = EXAMPLES_DIR / Path(entry["file"]).name
    info = validate_glb(path.read_bytes(), max_bytes=MAX_EXAMPLE_BYTES)
    assert info.triangle_count > 0
    assert info.vertex_count > 0


@pytest.mark.parametrize("entry", MANIFEST_ENTRIES, ids=lambda e: e["id"])
def test_manifest_metadata_matches_the_file(entry: dict):
    """Stated size and triangle count must match reality, since the UI shows them."""
    path = EXAMPLES_DIR / Path(entry["file"]).name
    data = path.read_bytes()
    info = validate_glb(data, max_bytes=MAX_EXAMPLE_BYTES)

    assert entry["byteSize"] == len(data), f"{entry['id']}: byteSize drifted"
    assert entry["triangleCount"] == info.triangle_count, (
        f"{entry['id']}: triangleCount drifted"
    )


@pytest.mark.parametrize("entry", MANIFEST_ENTRIES, ids=lambda e: e["id"])
def test_example_stays_within_size_budget(entry: dict):
    path = EXAMPLES_DIR / Path(entry["file"]).name
    assert path.stat().st_size <= MAX_EXAMPLE_BYTES


@pytest.mark.parametrize("entry", MANIFEST_ENTRIES, ids=lambda e: e["id"])
def test_example_is_served_from_the_static_examples_path(entry: dict):
    """Examples must be same-origin static files.

    That is what makes the browser honour the `download` attribute and keeps
    them working when the backend or its GPU provider is unavailable.
    """
    assert entry["file"].startswith("/examples/")
    assert entry["file"].endswith(".glb")


def test_example_ids_are_unique():
    ids = [e["id"] for e in MANIFEST_ENTRIES]
    assert len(ids) == len(set(ids))


def test_no_stray_files_in_examples_directory():
    """Everything shipped there should be a GLB the manifest knows about."""
    on_disk = {p.name for p in EXAMPLES_DIR.iterdir() if p.is_file()}
    declared = {Path(e["file"]).name for e in MANIFEST_ENTRIES}
    assert on_disk == declared, f"on disk {on_disk} != manifest {declared}"


def test_demo_assets_are_not_gitignored():
    """Regression: the root .gitignore excludes *.glb.

    Without an explicit negation the examples would be absent in production
    while working perfectly on a developer machine.
    """
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!frontend/public/examples/*.glb" in gitignore


def test_example_download_filenames_are_marked_as_examples():
    """`toModel` builds `formly-example-<id>.glb`; an example download must
    never look like an AI-generated asset on disk."""
    source = MANIFEST.read_text(encoding="utf-8")
    assert "formly-example-${example.id}.glb" in source


def test_examples_are_not_described_as_live_generation():
    """Guard the honesty requirement in the copy itself."""
    source = MANIFEST.read_text(encoding="utf-8")
    assert "not** produced at request time" in source or "not produced at request time" in source
    assert "pre-generated" in source.lower()
