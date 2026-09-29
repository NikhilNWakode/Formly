"""EXPERIMENTAL / UNVERIFIED: text-to-3D via a TRELLIS.2 Hugging Face Space.

    This provider has never completed a live generation. Its pipeline logic is
    covered by unit tests against a mocked Gradio client, but the free ZeroGPU
    allowance was exhausted during provider evaluation before a single
    end-to-end run could be made. It is opt-in via PROVIDER=trellis and is not
    reachable by users. Treat it as unproven until someone runs it with quota
    available. See "Provider evaluation" in the README.

Unlike Shap-E, TRELLIS is natively an *image*-to-3D model. The hosted Space
reaches text-to-3D by chaining three stages, which this provider drives in
order:

    prompt --/generate_txt2img--> image          [GPU]
          --/preprocess_image---> cleaned image  [no GPU allocation]
          --/generate_3d--------> GLB            [GPU]

That shape is the whole reason this is a separate provider rather than a
parameter on the Shap-E one: a multi-stage call sequence, session state, and a
different failure surface.

Cost, read from the Space's source rather than guessed: of the three stages,
exactly two carry `@spaces.GPU(size="xlarge", duration=120)` --
`generate_txt2img` and `generate_3d`. `preprocess_image` is not GPU-decorated.
One generation therefore reserves roughly 240 GPU-seconds on a large tier,
against Shap-E's single 60 s call.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import anyio

from app.services.generation.base import (
    GeneratedAsset,
    GenerationProvider,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.services.generation.hf_space import FailureKind, classify, is_retryable, result_path

logger = logging.getLogger(__name__)


class TrellisProvider(GenerationProvider):
    """Drives a TRELLIS.2 text-to-3D Space and returns GLB bytes.

    A fresh `gradio_client.Client` is built per generation rather than cached.
    The Space keeps per-session state (`/start_session`) across the three
    stages, so sharing one client between concurrent requests risks one
    request's image being consumed by another's 3D stage. The handshake costs a
    few seconds against a generation measured in minutes, which is a cheap
    price for not having to reason about cross-request state.
    """

    name = "trellis"

    def __init__(
        self,
        *,
        space: str = "prithivMLmods/TRELLIS.2-Text-to-3D",
        hf_token: str | None = None,
        resolution: str = "1024",
        texture_size: int = 1024,
        decimation_target: int = 150000,
        seed: int = 0,
        max_attempts: int = 2,
        backoff_seconds: float = 6.0,
        backoff_cap_seconds: float = 12.0,
        timeout_seconds: float = 600.0,
    ) -> None:
        self._space = space
        self._hf_token = hf_token
        self._resolution = resolution
        self._texture_size = texture_size
        self._decimation_target = decimation_target
        self._seed = seed
        # Fewer attempts than Shap-E on purpose: each retry burns ~240
        # GPU-seconds of a shared free quota (two GPU stages at duration=120)
        # and several minutes of user time.
        self._max_attempts = max(1, max_attempts)
        self._backoff = backoff_seconds
        self._backoff_cap = backoff_cap_seconds
        self._timeout = timeout_seconds

    # -- pipeline -------------------------------------------------------------

    def _build_client_sync(self):
        from gradio_client import Client

        kwargs: dict = {"verbose": False}
        if self._hf_token:
            # gradio_client 2.x renamed `hf_token` to `token`; see the contract
            # test in tests/test_providers.py.
            kwargs["token"] = self._hf_token
        return Client(self._space, **kwargs)

    def _run_pipeline_sync(self, prompt: str) -> bytes:
        """Execute the three-stage pipeline. Runs entirely in a worker thread."""
        from gradio_client import handle_file

        client = self._build_client_sync()

        # Session state is what ties the three stages together. A Space that
        # does not expose it still works, so a failure here is not fatal.
        try:
            client.predict(api_name="/start_session")
        except Exception as exc:  # noqa: BLE001
            logger.debug("trellis start_session skipped: %s", str(exc)[:120])

        stage_started = time.perf_counter()
        image = client.predict(prompt=prompt, api_name="/generate_txt2img")
        image_path = result_path(image)
        if not image_path or not Path(image_path).exists():
            raise ProviderUnavailableError(f"txt2img returned no image (got {image!r})")
        logger.info(
            "trellis_stage stage=txt2img seconds=%.1f", time.perf_counter() - stage_started
        )

        stage_started = time.perf_counter()
        cleaned = client.predict(input=handle_file(image_path), api_name="/preprocess_image")
        cleaned_path = result_path(cleaned) or image_path
        logger.info(
            "trellis_stage stage=preprocess seconds=%.1f", time.perf_counter() - stage_started
        )

        stage_started = time.perf_counter()
        result = client.predict(
            image=handle_file(cleaned_path),
            seed=self._seed,
            resolution=self._resolution,
            decimation_target=self._decimation_target,
            texture_size=self._texture_size,
            ss_guidance_strength=7.5,
            ss_guidance_rescale=0.7,
            ss_sampling_steps=12,
            ss_rescale_t=5.0,
            shape_guidance=7.5,
            shape_rescale=0.5,
            shape_steps=12,
            shape_rescale_t=3.0,
            tex_guidance=1.0,
            tex_rescale=0.0,
            tex_steps=12,
            tex_rescale_t=3.0,
            api_name="/generate_3d",
        )
        logger.info(
            "trellis_stage stage=generate_3d seconds=%.1f", time.perf_counter() - stage_started
        )

        # `/generate_3d` returns a viewer payload alongside the download file,
        # so pick the GLB explicitly instead of trusting positional order.
        glb_path = None
        for item in result if isinstance(result, (list, tuple)) else [result]:
            candidate = result_path(item)
            if candidate and str(candidate).lower().endswith(".glb"):
                glb_path = candidate
                break

        if not glb_path or not Path(glb_path).exists():
            raise ProviderUnavailableError(
                f"generate_3d returned no GLB (got {str(result)[:160]})"
            )

        data = Path(glb_path).read_bytes()

        # gradio_client downloads into a temp dir; drop the copies so a
        # long-running instance does not accumulate them.
        for path in {image_path, cleaned_path, glb_path}:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                logger.debug("could not remove provider temp file %s", path)

        return data

    # -- provider API ---------------------------------------------------------

    async def generate(self, prompt: str) -> GeneratedAsset:
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            started = time.perf_counter()
            try:
                with anyio.fail_after(self._timeout):
                    # abandon_on_cancel=True is required for the timeout to
                    # fire at all; see the note in shap_e.py.
                    data = await anyio.to_thread.run_sync(
                        self._run_pipeline_sync, prompt, abandon_on_cancel=True
                    )

                latency = time.perf_counter() - started
                logger.info(
                    "provider_call_ok provider=%s attempt=%s bytes=%s latency=%.2fs",
                    self.name,
                    attempt,
                    len(data),
                    latency,
                )
                return GeneratedAsset(
                    data=data, fmt="glb", provider=self.name, latency_seconds=latency
                )

            except TimeoutError as exc:
                logger.warning("provider_timeout provider=%s attempt=%s", self.name, attempt)
                raise ProviderTimeoutError(
                    f"{self._space} timed out after {self._timeout}s"
                ) from exc

            except TypeError as exc:
                logger.error(
                    "provider_call_signature_error provider=%s error=%s", self.name, exc
                )
                raise ProviderUnavailableError(
                    f"{self._space} called incorrectly: {exc}"
                ) from exc

            except Exception as exc:  # noqa: BLE001 - gradio raises bare Exceptions
                last_error = exc
                kind = classify(exc)
                logger.warning(
                    "provider_call_failed provider=%s attempt=%s/%s kind=%s error=%s",
                    self.name,
                    attempt,
                    self._max_attempts,
                    kind.value,
                    str(exc)[:200],
                )

                if kind is FailureKind.QUOTA:
                    raise ProviderUnavailableError(
                        f"{self._space} quota exceeded: {exc}",
                        public_message="The generation service is busy right now",
                    ) from exc

                if kind is FailureKind.REFUSED:
                    raise ProviderUnavailableError(
                        f"{self._space} refused the request: {exc}"
                    ) from exc

                if is_retryable(kind) and attempt < self._max_attempts:
                    await anyio.sleep(min(self._backoff * attempt, self._backoff_cap))
                    continue
                break

        raise ProviderUnavailableError(
            f"{self._space} failed after {self._max_attempts} attempts: {last_error}"
        )
