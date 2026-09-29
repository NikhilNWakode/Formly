"""Provider-agnostic contract for text-to-3D generation.

Everything above this module (routes, schemas, the frontend) depends only on
`GenerationProvider` and `GeneratedAsset`. Swapping Shap-E for TRELLIS, a
Replicate model, or a self-hosted GPU worker means adding one class here and
changing `FORMLY_PROVIDER` -- no route or UI changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratedAsset:
    """A 3D asset produced by a provider.

    `data` holds the raw bytes rather than a path so providers that stream from
    an HTTP response never need to touch the filesystem.
    """

    data: bytes
    fmt: str = "glb"
    provider: str = "unknown"
    latency_seconds: float = 0.0


class GenerationError(Exception):
    """Base class for generation failures.

    `public_message` is safe to show a user. `str(exc)` may contain provider
    detail and belongs only in logs.
    """

    public_message = "Unable to generate model"

    def __init__(self, message: str, *, public_message: str | None = None):
        super().__init__(message)
        if public_message:
            self.public_message = public_message


class ProviderUnavailableError(GenerationError):
    """Upstream provider is unreachable, asleep, or out of quota."""

    public_message = "The generation service is unavailable"


class ProviderTimeoutError(GenerationError):
    """Provider accepted the job but did not return in time."""

    public_message = "Generation took too long"


class InvalidAssetError(GenerationError):
    """Provider returned something that is not a usable 3D asset."""

    public_message = "The generated model could not be loaded"


class GenerationProvider(ABC):
    """A text-to-3D backend."""

    name: str = "base"

    @property
    def space(self) -> str | None:
        """Upstream host this provider calls, for health output and logs.

        Reported so an operator can tell which Space is actually in use --
        reading it off one provider's settings would misreport the moment a
        second provider exists.
        """
        return getattr(self, "_space", None)

    @abstractmethod
    async def generate(self, prompt: str) -> GeneratedAsset:
        """Generate a 3D asset from a natural-language prompt.

        Raises a `GenerationError` subclass on failure. Must never return a
        placeholder or partial asset.
        """

    async def aclose(self) -> None:
        """Release provider resources. Called on application shutdown."""
