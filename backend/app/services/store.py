"""In-process, TTL-bounded store for generated assets.

Why not a database or object storage: a generated model is only needed between
the POST that creates it and the GET that renders/downloads it, and the product
deliberately keeps no generation history. A bounded dict plus a temp directory
covers that with no extra infrastructure.

The tradeoff is explicit: assets do not survive a restart and are not shared
between server instances. That is acceptable for a single-instance deployment
and is the first thing to replace with object storage when moving to workers.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredAsset:
    asset_id: str
    path: Path
    filename: str
    media_type: str
    created_at: float
    byte_size: int


class AssetStore:
    """Thread-safe, size- and time-bounded asset store backed by a temp dir."""

    def __init__(self, *, ttl_seconds: int = 3600, max_items: int = 64) -> None:
        self._ttl = ttl_seconds
        self._max_items = max_items
        self._lock = threading.Lock()
        self._items: dict[str, StoredAsset] = {}
        self._dir = Path(tempfile.mkdtemp(prefix="formly-assets-"))
        logger.info("asset_store_ready dir=%s ttl=%ss max=%s", self._dir, ttl_seconds, max_items)

    def put(self, asset_id: str, data: bytes, *, filename: str, media_type: str) -> StoredAsset:
        path = self._dir / f"{asset_id}.glb"
        path.write_bytes(data)
        asset = StoredAsset(
            asset_id=asset_id,
            path=path,
            filename=filename,
            media_type=media_type,
            created_at=time.time(),
            byte_size=len(data),
        )
        with self._lock:
            self._items[asset_id] = asset
            self._evict_locked()
        return asset

    def get(self, asset_id: str) -> StoredAsset | None:
        with self._lock:
            asset = self._items.get(asset_id)
            if asset is None:
                return None
            if self._is_expired(asset):
                self._remove_locked(asset_id)
                return None
        # A restart or manual cleanup can remove the file behind our back.
        if not asset.path.exists():
            with self._lock:
                self._remove_locked(asset_id)
            return None
        return asset

    def _is_expired(self, asset: StoredAsset) -> bool:
        return (time.time() - asset.created_at) > self._ttl

    def _remove_locked(self, asset_id: str) -> None:
        asset = self._items.pop(asset_id, None)
        if asset is None:
            return
        try:
            asset.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("asset_cleanup_failed id=%s error=%s", asset_id, exc)

    def _evict_locked(self) -> None:
        """Drop expired entries, then the oldest entries past the size cap."""
        for asset_id in [k for k, v in self._items.items() if self._is_expired(v)]:
            self._remove_locked(asset_id)

        while len(self._items) > self._max_items:
            oldest = min(self._items, key=lambda k: self._items[k].created_at)
            self._remove_locked(oldest)

    def clear(self) -> None:
        with self._lock:
            for asset_id in list(self._items):
                self._remove_locked(asset_id)
