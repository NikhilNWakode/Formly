"""Shared helpers for providers backed by a Hugging Face Space.

Both Space-backed providers hit the same operational realities -- containers
that sleep and return 502, a shared ZeroGPU quota, and `gradio_client` raising
bare `Exception` with the reason only in the message text. The classification
of those failures is identical for every Space, so it lives here rather than
being copy-pasted per provider.

Retry *loops* deliberately stay in the providers: Shap-E is a single cached
call, while TRELLIS is a multi-step pipeline with its own session handling.
"""

from __future__ import annotations

from enum import Enum

# Substrings indicating a sleeping or flapping Space rather than a bad request.
_TRANSIENT_MARKERS = (
    "502",
    "bad gateway",
    "could not get gradio config",
    "could not fetch config",
    "could not fetch api info",
    "connection",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "upstream",
    "internal server error",
)

# ZeroGPU quota exhaustion. Retrying these only makes the user wait longer.
_QUOTA_MARKERS = (
    "quota",
    "exceeded",
    "rate limit",
    "too many requests",
    "zerogpu",
)

# The Space accepted the call but refused the feature (e.g. Hunyuan3D-2 reports
# "Text to 3D is disable"). A retry cannot fix a server-side feature flag.
_REFUSED_MARKERS = (
    "is disable",
    "is disabled",
    "not enabled",
    "not supported",
)


class FailureKind(str, Enum):
    TRANSIENT = "transient"
    QUOTA = "quota"
    REFUSED = "refused"
    UNKNOWN = "unknown"


def classify(exc: Exception) -> FailureKind:
    """Classify a `gradio_client` failure by its message text.

    Order matters: quota and refusal messages can also contain words that look
    transient, and neither is worth retrying.
    """
    message = str(exc).lower()

    if any(marker in message for marker in _QUOTA_MARKERS):
        return FailureKind.QUOTA
    if any(marker in message for marker in _REFUSED_MARKERS):
        return FailureKind.REFUSED
    if any(marker in message for marker in _TRANSIENT_MARKERS):
        return FailureKind.TRANSIENT
    # Unknown failures are retried: the Spaces surface varied error strings and
    # a retry is cheap relative to failing a generation the user is waiting on.
    return FailureKind.UNKNOWN


def is_retryable(kind: FailureKind) -> bool:
    return kind in (FailureKind.TRANSIENT, FailureKind.UNKNOWN)


def result_path(value: object) -> str | None:
    """Extract a local file path from a gradio return value.

    Gradio returns plain paths, `{"path": ...}` dicts, or tuples of either
    depending on the component and version.
    """
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        path = value.get("path") or value.get("url")
        return path if isinstance(path, str) and path else None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = result_path(item)
            if found:
                return found
    return None
