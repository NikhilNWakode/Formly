"""Request and response models for the generation API."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# Conservative allowlist: letters, digits, whitespace and common punctuation.
# Blocks control characters and angle brackets without fighting real prompts.
_DISALLOWED = re.compile("[<>{}]|[\x00-\x1f\x7f]|" + re.escape("\\"))

PROMPT_MIN = 3
PROMPT_MAX = 300


class GenerateRequest(BaseModel):
    prompt: str = Field(
        ...,
        description="Natural-language description of the object to generate.",
        examples=["A futuristic cyberpunk helmet"],
    )

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        # Collapse whitespace first so "   " is treated as empty and multi-line
        # pastes become a single clean prompt.
        cleaned = " ".join(value.split())

        if not cleaned:
            raise ValueError("Please describe the object you want to create.")
        if len(cleaned) < PROMPT_MIN:
            raise ValueError(f"Prompt must be at least {PROMPT_MIN} characters.")
        if len(cleaned) > PROMPT_MAX:
            raise ValueError(f"Prompt must be {PROMPT_MAX} characters or fewer.")
        if _DISALLOWED.search(cleaned):
            raise ValueError("Prompt contains unsupported characters.")
        return cleaned


class GenerateResponse(BaseModel):
    success: bool = True
    model_url: str = Field(description="Relative URL the client fetches the GLB from.")
    download_url: str = Field(description="Relative URL that forces a download.")
    filename: str = Field(description="Suggested filename, already sanitized.")
    fmt: str = Field(default="glb", alias="format", serialization_alias="format")
    prompt: str
    provider: str
    generation_seconds: float = Field(description="Measured end-to-end provider latency.")
    vertex_count: int
    triangle_count: int
    byte_size: int

    model_config = {"populate_by_name": True}


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
