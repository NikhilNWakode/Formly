"""Liveness endpoint.

Deliberately does not call the AI provider: free hosts poll this frequently and
waking a sleeping GPU Space on every health check would burn shared quota.

The consequence is stated in the payload rather than left implicit. A 200 here
means *this API process is up*, and nothing more. The upstream Space is known
to flap between healthy and 502 while still reporting itself as running, so a
health response that implied upstream health would be actively misleading --
the only honest report is that it was not checked.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.config import Settings, get_settings

router = APIRouter()


@router.get("/health", summary="Liveness probe for this API only")
async def health(request: Request, settings: Settings = Depends(get_settings)) -> dict:
    provider = request.app.state.provider
    return {
        # Refers to this process, not to the generation pipeline end to end.
        "status": "ok",
        "scope": "api-only",
        "format": "glb",
        "provider": {
            "name": provider.name,
            # Read off the live provider, not settings: with more than one
            # provider configured, settings.hf_space would report the wrong host.
            "space": provider.space,
            # Never probed here. Upstream availability is only discovered when a
            # real generation runs, and it changes minute to minute.
            "upstream_health": "not_checked",
        },
    }
