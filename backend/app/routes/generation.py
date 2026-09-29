"""Generation and asset-serving endpoints."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.schemas.generation import GenerateRequest, GenerateResponse
from app.services.generation.base import GenerationError, GenerationProvider
from app.services.generation.validator import AssetValidationError, validate_glb
from app.services.naming import build_filename
from app.services.store import AssetStore

logger = logging.getLogger("formly.generation")

router = APIRouter()

GLB_MEDIA_TYPE = "model/gltf-binary"


def get_provider(request: Request) -> GenerationProvider:
    return request.app.state.provider


def get_store(request: Request) -> AssetStore:
    return request.app.state.store


def _client_key(request: Request) -> str:
    # Behind a single reverse proxy on the target hosts, the leftmost
    # X-Forwarded-For entry is the closest thing to a client identity we have.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post(
    "/generate",
    response_model=GenerateResponse,
    response_model_by_alias=True,
    summary="Generate a 3D model from a text prompt",
)
async def generate(
    payload: GenerateRequest,
    request: Request,
    response: Response,
    provider: GenerationProvider = Depends(get_provider),
    store: AssetStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> GenerateResponse:
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
    prompt = payload.prompt
    started = time.perf_counter()

    limiter = request.app.state.limiter
    key = _client_key(request)
    if not limiter.allow(key):
        retry_after = limiter.retry_after(key)
        logger.warning("rate_limited request_id=%s retry_after=%s", request_id, retry_after)
        raise HTTPException(
            status_code=429,
            detail="Too many generations from this client. Please wait a moment.",
            headers={"Retry-After": str(retry_after)},
        )

    logger.info(
        "generation_started request_id=%s provider=%s prompt_length=%s",
        request_id,
        provider.name,
        len(prompt),
    )

    try:
        asset = await provider.generate(prompt)
    except GenerationError as exc:
        duration = time.perf_counter() - started
        logger.warning(
            "generation_failed request_id=%s provider=%s duration=%.2fs reason=%s detail=%s",
            request_id,
            provider.name,
            duration,
            type(exc).__name__,
            str(exc)[:300],
        )
        # 502: we are a healthy gateway reporting a failing upstream.
        raise HTTPException(status_code=502, detail=exc.public_message) from exc
    except Exception as exc:  # noqa: BLE001 - last line of defence
        duration = time.perf_counter() - started
        logger.exception(
            "generation_crashed request_id=%s provider=%s duration=%.2fs",
            request_id,
            provider.name,
            duration,
        )
        raise HTTPException(status_code=500, detail="Unable to generate model") from exc

    # Never trust provider output: an HTML error page or a truncated download
    # would otherwise reach the browser as a broken model.
    try:
        info = validate_glb(
            asset.data,
            min_bytes=settings.min_asset_bytes,
            max_bytes=settings.max_asset_bytes,
        )
    except AssetValidationError as exc:
        duration = time.perf_counter() - started
        logger.warning(
            "validation_failed request_id=%s provider=%s duration=%.2fs bytes=%s reason=%s",
            request_id,
            provider.name,
            duration,
            len(asset.data),
            exc,
        )
        raise HTTPException(
            status_code=502, detail="The generated model could not be loaded"
        ) from exc

    asset_id = uuid.uuid4().hex
    filename = build_filename(prompt)
    store.put(asset_id, asset.data, filename=filename, media_type=GLB_MEDIA_TYPE)

    duration = time.perf_counter() - started
    logger.info(
        "generation_completed request_id=%s provider=%s asset_id=%s duration=%.2fs "
        "generation_latency=%.2fs bytes=%s vertices=%s triangles=%s materials=%s",
        request_id,
        provider.name,
        asset_id,
        duration,
        asset.latency_seconds,
        info.byte_size,
        info.vertex_count,
        info.triangle_count,
        info.material_count,
    )

    response.headers["X-Request-ID"] = request_id
    return GenerateResponse(
        success=True,
        model_url=f"/api/models/{asset_id}.glb",
        download_url=f"/api/models/{asset_id}/download",
        filename=filename,
        format="glb",
        prompt=prompt,
        provider=provider.name,
        generation_seconds=round(asset.latency_seconds, 2),
        vertex_count=info.vertex_count,
        triangle_count=info.triangle_count,
        byte_size=info.byte_size,
    )


def _lookup(store: AssetStore, asset_id: str):
    asset = store.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Model not found or expired")
    return asset


@router.get("/models/{asset_id}.glb", summary="Fetch a generated GLB for rendering")
async def get_model(asset_id: str, store: AssetStore = Depends(get_store)) -> FileResponse:
    asset = _lookup(store, asset_id)
    return FileResponse(
        asset.path,
        media_type=GLB_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'inline; filename="{asset.filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/models/{asset_id}/download", summary="Download a generated GLB")
async def download_model(asset_id: str, store: AssetStore = Depends(get_store)) -> FileResponse:
    asset = _lookup(store, asset_id)
    return FileResponse(
        asset.path,
        media_type=GLB_MEDIA_TYPE,
        filename=asset.filename,
        headers={"Cache-Control": "private, max-age=3600"},
    )
