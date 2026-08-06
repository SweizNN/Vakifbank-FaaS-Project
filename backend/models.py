"""
models.py — Pydantic request/response models
=============================================
All API input/output schemas live here, keeping main.py free of
validation logic and making models independently importable for tests.
"""

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from config import SUPPORTED_LANGUAGES

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,49}$")


def validate_function_name(v: str) -> str:
    """Shared by every model that carries a function name (`DeployRequest`,
    `SqlDeployRequest`, and the ad-hoc regex checks routers run on path params)."""
    if not _NAME_RE.match(v):
        raise ValueError(
            "Function name must start with a lowercase letter and "
            "contain only lowercase letters, digits, and hyphens."
        )
    return v


class DeployRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)
    language: str
    code: str = Field(..., min_length=5)
    user_snippet: Optional[str] = Field(None)   # raw editor content before wrapCode
    config_yaml: Optional[str] = Field(None)
    is_update: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_function_name(v)

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{v}'. Choose from: {SUPPORTED_LANGUAGES}"
            )
        return v


class SqlDeployRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)
    db_type: Literal["postgres", "mysql"]
    db_host: str = Field(..., min_length=1, max_length=255)
    db_port: int = Field(..., ge=1, le=65535)
    db_name: str = Field(..., min_length=1, max_length=128)
    db_user: str = Field(..., min_length=1, max_length=128)
    db_password: str = Field(..., min_length=1, max_length=512)
    sql_query: str = Field(..., min_length=1, max_length=20000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_function_name(v)


class DeleteResponse(BaseModel):
    message: str
    function_name: str


class ProxyRequest(BaseModel):
    url: str
    method: str = "POST"
    headers: dict = {}
    body: dict = {}
