"""Text-to-3D via the `hysts/Shap-E` Hugging Face Space.

Why a Space and not the HF Inference API: as of this build no serverless
inference provider serves any text-to-3D model (`openai/shap-e` reports an
empty `inferenceProviderMapping`), so a hosted Space is the only free remote
path that needs no GPU of our own.

Operational note that shapes this file: ZeroGPU Spaces sleep. A cold Space
returns HTTP 502 for the first requests while its container boots, then serves
normally. That was measured repeatedly during development, so connect+predict
is retried with backoff instead of surfacing a spurious failure to the user.
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
from app.services.generation.hf_space import FailureKind, classify

logger = logging.getLogger(__name__)

class ShapEProvider(GenerationProvider):
    """Calls the Shap-E Space's `/text-to-3d` endpoint and returns GLB bytes.

    `gradio_client` is synchronous, so every call is dispatched to a worker
    thread to keep the event loop free. The `Client` handshake is cached and
    reused across requests, and dropped whenever a call fails so a restarted
    Space cannot leave us holding a stale config.
    """

    name = "shap-e"

    def __init__(
        self,
        *,
        space: str = "hysts/Shap-E",
        hf_token: str | None = None,
        inference_steps: int = 64,
        guidance_scale: float = 15.0,
        max_attempts: int = 6,
        backoff_seconds: float = 4.0,
        backoff_cap_seconds: float = 10.0,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._space = space
        self._hf_token = hf_token
        self._inference_steps = inference_steps
        self._guidance_scale = guidance_scale
        self._max_attempts = max(1, max_attempts)
        self._backoff = backoff_seconds
        self._backoff_cap = backoff_cap_seconds
        self._timeout = timeout_seconds
        self._client = None
        self._client_lock = anyio.Lock()

    # -- client lifecycle -----------------------------------------------------

    def _build_client_sync(self):
        from gradio_client import Client

        kwargs: dict = {"verbose": False}
        if self._hf_token:
            # gradio_client 2.x renamed this from `hf_token` to `token`.
            # `test_client_accepts_the_token_kwarg_we_pass` guards the rename so
            # a dependency bump cannot break this silently -- this path only
            # runs when a token is configured, so it is invisible to anonymous
            # testing.
            kwargs["token"] = self._hf_token
        return Client(self._space, **kwargs)

    async def _get_client(self):
        async with self._client_lock:
            if self._client is None:
                self._client = await anyio.to_thread.run_sync(self._build_client_sync)
            return self._client

    async def _drop_client(self) -> None:
        async with self._client_lock:
            self._client = None

    # -- generation -----------------------------------------------------------

    def _predict_sync(self, client, prompt: str) -> bytes:
        result = client.predict(
            prompt=prompt,
            seed=0,
            guidance_scale=self._guidance_scale,
            num_inference_steps=self._inference_steps,
            api_name="/text-to-3d",
        )

        # Gradio returns a local filepath for Model3d outputs; newer versions may
        # wrap it in a dict.
        path = result.get("path") if isinstance(result, dict) else result
        if not isinstance(path, str) or not path:
            raise ProviderUnavailableError(f"provider returned no file path (got {result!r})")

        file_path = Path(path)
        if not file_path.exists():
            raise ProviderUnavailableError(f"provider file path does not exist: {path}")

        data = file_path.read_bytes()

        # gradio_client downloads into a temp dir; clean up so long-running
        # instances do not accumulate multi-megabyte files.
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("could not remove provider temp file %s", path)

        return data

    async def generate(self, prompt: str) -> GeneratedAsset:
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            started = time.perf_counter()
            try:
                client = await self._get_client()
                with anyio.fail_after(self._timeout):
                    # abandon_on_cancel=True is load-bearing: without it the
                    # worker thread is shielded from cancellation and the
                    # timeout never fires, so a hung Space would hang the
                    # request indefinitely. The tradeoff is that a timed-out
                    # thread keeps running until the provider call returns.
                    data = await anyio.to_thread.run_sync(
                        self._predict_sync, client, prompt, abandon_on_cancel=True
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
                # Do not retry a timeout: the next attempt would blow the same budget.
                await self._drop_client()
                logger.warning("provider_timeout provider=%s attempt=%s", self.name, attempt)
                raise ProviderTimeoutError(f"{self._space} timed out after {self._timeout}s") from exc

            except TypeError as exc:
                # A bad call signature is our bug, not a flaky upstream.
                # Retrying it just makes the user wait three times as long.
                await self._drop_client()
                logger.error(
                    "provider_call_signature_error provider=%s error=%s", self.name, exc
                )
                raise ProviderUnavailableError(
                    f"{self._space} called incorrectly: {exc}"
                ) from exc

            except Exception as exc:  # noqa: BLE001 - provider raises bare Exceptions
                last_error = exc
                await self._drop_client()
                kind = classify(exc)

                if kind is FailureKind.QUOTA:
                    logger.warning(
                        "provider_quota provider=%s attempt=%s error=%s",
                        self.name,
                        attempt,
                        str(exc)[:200],
                    )
                    raise ProviderUnavailableError(
                        f"{self._space} quota exceeded: {exc}",
                        public_message="The generation service is busy right now",
                    ) from exc

                if kind is FailureKind.REFUSED:
                    # The Space answered but the feature is switched off
                    # server-side; retrying cannot change that.
                    logger.error(
                        "provider_refused provider=%s error=%s", self.name, str(exc)[:200]
                    )
                    raise ProviderUnavailableError(
                        f"{self._space} refused the request: {exc}"
                    ) from exc

                transient = kind is FailureKind.TRANSIENT
                logger.warning(
                    "provider_call_failed provider=%s attempt=%s/%s transient=%s error=%s",
                    self.name,
                    attempt,
                    self._max_attempts,
                    transient,
                    str(exc)[:200],
                )

                if attempt < self._max_attempts:
                    # Capped linear backoff. The Space's failures are not time
                    # correlated -- it alternates healthy and 502 within
                    # seconds -- so long waits do not improve the odds, they
                    # just make the user wait. More attempts sooner is what
                    # actually lands a healthy replica; the cap keeps the tail
                    # bounded without hammering a shared free service.
                    await anyio.sleep(min(self._backoff * attempt, self._backoff_cap))
                    continue
                break

        raise ProviderUnavailableError(
            f"{self._space} failed after {self._max_attempts} attempts: {last_error}"
        )

    async def aclose(self) -> None:
        await self._drop_client()
