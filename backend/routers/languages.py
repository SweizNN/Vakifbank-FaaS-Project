"""routers/languages.py — supported code-editor runtimes."""

from fastapi import APIRouter

from config import LANGUAGE_CONFIG

router = APIRouter(tags=["languages"])


@router.get("/languages", summary="List supported runtimes")
async def list_languages():
    """Return all supported runtime languages with their template and entrypoint."""
    return {
        lang: {
            "template": cfg["template"],
            "entrypoint": cfg["entrypoint"],
            "description": cfg["description"],
        }
        for lang, cfg in LANGUAGE_CONFIG.items()
    }
