"""
models.py — Pydantic request/response models
=============================================
All API input/output schemas live here, keeping main.py free of
validation logic and making models independently importable for tests.
"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from config import SUPPORTED_LANGUAGES


class DeployRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)
    language: str
    code: str = Field(..., min_length=5)
    user_snippet: Optional[str] = Field(None)   # raw editor content before wrapCode
    config_yaml: Optional[str] = Field(None)
    description: Optional[str] = Field(None, max_length=200)
    is_update: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9-]{2,49}$", v):
            raise ValueError(
                "Function name must start with a lowercase letter and "
                "contain only lowercase letters, digits, and hyphens."
            )
        return v

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{v}'. Choose from: {SUPPORTED_LANGUAGES}"
            )
        return v


class DeleteResponse(BaseModel):
    message: str
    function_name: str


class ProxyRequest(BaseModel):
    url: str
    method: str = "POST"
    headers: dict = {}
    body: dict = {}
