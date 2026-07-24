"""ASGI compatibility entry point: ``uvicorn main:app``."""

from seo_analyzer.api import app

__all__ = ["app"]
