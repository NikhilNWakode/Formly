"""Provider selection.

Kept deliberately small: one mapping from a settings string to a concrete
provider. Adding a provider means adding one entry here and one module --
nothing in the routes, schemas or frontend changes.

There is no automatic fallback between providers. A silent switch would hide
which model produced a result and could double an already slow generation, so
the choice stays explicit and environment-driven.
"""

from __future__ import annotations

from app.config import Settings
from app.services.generation.base import GenerationProvider
from app.services.generation.shap_e import ShapEProvider
from app.services.generation.trellis import TrellisProvider

#: Provider ids accepted by the `PROVIDER` environment variable.
AVAILABLE_PROVIDERS = ("shap-e", "trellis")


def build_provider(settings: Settings) -> GenerationProvider:
    if settings.provider == "shap-e":
        return ShapEProvider(
            space=settings.hf_space,
            hf_token=settings.hf_token,
            inference_steps=settings.inference_steps,
            guidance_scale=settings.guidance_scale,
            max_attempts=settings.provider_max_attempts,
            backoff_seconds=settings.provider_backoff_seconds,
            backoff_cap_seconds=settings.provider_backoff_cap_seconds,
            timeout_seconds=settings.provider_timeout_seconds,
        )

    if settings.provider == "trellis":
        return TrellisProvider(
            space=settings.trellis_space,
            hf_token=settings.hf_token,
            resolution=settings.trellis_resolution,
            texture_size=settings.trellis_texture_size,
            decimation_target=settings.trellis_decimation_target,
            max_attempts=settings.trellis_max_attempts,
            backoff_seconds=settings.provider_backoff_seconds,
            backoff_cap_seconds=settings.provider_backoff_cap_seconds,
            timeout_seconds=settings.trellis_timeout_seconds,
        )

    raise ValueError(
        f"Unknown generation provider: {settings.provider!r}. "
        f"Expected one of {', '.join(AVAILABLE_PROVIDERS)}."
    )
