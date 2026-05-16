"""
Настройки доступа к OpenAI: напрямую или через ProxyAPI (https://proxyapi.ru).

В .env для ProxyAPI:
  OPENAI_API_PROVIDER=proxyapi
  PROXYAPI_KEY=ваш_ключ

Ключ ProxyAPI можно также передать как OPENAI_API_KEY, если провайдер уже proxyapi.
"""

from __future__ import annotations

import os

# Нативный OpenAI API ProxyAPI — те же имена моделей (gpt-4o-mini, text-embedding-3-small)
PROXYAPI_DEFAULT_BASE_URL = "https://api.proxyapi.ru/openai/v1"


def proxyapi_enabled() -> bool:
    provider = os.getenv("OPENAI_API_PROVIDER", "").strip().lower()
    if provider == "proxyapi":
        return True
    flag = os.getenv("USE_PROXYAPI", "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def resolve_openai_api_key() -> str | None:
    """Ключ для SDK OpenAI (прямой OpenAI или ProxyAPI)."""
    if proxyapi_enabled():
        key = (os.getenv("PROXYAPI_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        return key or None
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    return key or None


def resolve_openai_base_url() -> str | None:
    """Base URL для SDK; None — официальный api.openai.com."""
    explicit = os.getenv("OPENAI_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    if proxyapi_enabled():
        custom = os.getenv("PROXYAPI_BASE_URL", "").strip()
        return (custom or PROXYAPI_DEFAULT_BASE_URL).rstrip("/")
    return None


def require_openai_api_key() -> str:
    key = resolve_openai_api_key()
    if not key:
        if proxyapi_enabled():
            raise ValueError(
                "Не задан ключ ProxyAPI. Укажите PROXYAPI_KEY или OPENAI_API_KEY в .env"
            )
        raise ValueError("OPENAI_API_KEY не установлен")
    return key
