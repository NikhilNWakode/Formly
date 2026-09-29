"""Application settings, loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Every value has a working default so the app boots with no .env file.
    Secrets (HF_TOKEN) are read from the environment only and never returned
    to the client.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Generation provider -------------------------------------------------
    # Which GenerationProvider implementation to use. See services/generation/registry.py
    provider: str = "shap-e"

    # Hugging Face Space backing the default provider.
    hf_space: str = "hysts/Shap-E"

    # Optional. Anonymous access to ZeroGPU Spaces works but is rate limited per
    # IP; a free read token raises the quota and makes generation far more
    # reliable. Never sent to the browser.
    #
    # repr=False keeps it out of Settings' repr, so it cannot leak into a
    # traceback, a log line or a test failure -- which is exactly how it
    # surfaced before this was set.
    hf_token: str | None = Field(default=None, repr=False)

    # Shap-E sampling parameters. 64 steps is the Space default and the quality
    # knee; higher values cost latency without much visible gain.
    inference_steps: int = 64
    guidance_scale: float = 15.0

    # --- TRELLIS provider (EXPERIMENTAL, opt-in: PROVIDER=trellis) -----------
    # Unverified: no live generation has ever completed through this provider,
    # so no claim is made about its output quality relative to Shap-E.
    #
    # One generation drives three pipeline stages, two of which consume GPU
    # quota (`generate_txt2img` and `generate_3d`, each declaring
    # `@spaces.GPU(size="xlarge", duration=120)`); `preprocess_image` is not
    # GPU-decorated. That is ~240 GPU-seconds on a large tier against Shap-E's
    # single 60 s call, so it exhausts a free ZeroGPU allowance far faster.
    # Not the default; see the provider evaluation in the README.
    trellis_space: str = "prithivMLmods/TRELLIS.2-Text-to-3D"
    trellis_resolution: str = "1024"
    trellis_texture_size: int = 1024
    trellis_decimation_target: int = 150000
    # Deliberately fewer retries than Shap-E: each attempt costs minutes of
    # user time and a large slice of shared quota.
    trellis_max_attempts: int = 2
    trellis_timeout_seconds: float = 600.0

    # --- Reliability ---------------------------------------------------------
    # ZeroGPU Spaces sleep and return 502 while waking. We retry the whole
    # connect+predict cycle rather than failing the user's request.
    #
    # Budget tuned against the real Space, which alternates healthy and 502
    # within seconds rather than failing for a sustained period. Because the
    # failures are not time correlated, more attempts sooner beats fewer
    # attempts spread further apart: a 3-attempt/4s budget (~26s) and a
    # 4-attempt/10s budget (~60s) both gave up while the Space was still
    # serving intermittently, and a direct call succeeded on its 2nd try.
    # Backoff is linear but capped, so the worst case stays bounded without
    # hammering a shared free service.
    provider_max_attempts: int = 6
    provider_backoff_seconds: float = 4.0
    provider_backoff_cap_seconds: float = 10.0
    provider_timeout_seconds: float = 300.0

    # --- Asset store ---------------------------------------------------------
    asset_ttl_seconds: int = 3600
    max_stored_assets: int = 64

    # --- Validation ----------------------------------------------------------
    prompt_min_length: int = 3
    prompt_max_length: int = 300
    min_asset_bytes: int = 1024
    max_asset_bytes: int = 100 * 1024 * 1024

    # --- HTTP ----------------------------------------------------------------
    # Comma-separated exact origins. Falls back to localhost for development.
    # In production set CORS_ORIGINS to the deployed frontend URL.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Optional regex for origins that cannot be enumerated ahead of time.
    # Vercel mints a new hashed subdomain per deployment
    # (project-<hash>-<team>.vercel.app), so an exact list breaks on every
    # redeploy. Keep the pattern scoped to your own project rather than all of
    # *.vercel.app, which would let any site hosted there call this API.
    #
    #   CORS_ORIGIN_REGEX=https://myproject(-[a-z0-9-]+)?\.vercel\.app
    cors_origin_regex: str | None = None

    # Simple in-process abuse guard: max generations per client IP per window.
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
