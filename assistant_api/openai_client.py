"""
Единая фабрика клиента OpenAI: прямой API или ProxyAPI (OPENAI_API_PROVIDER=proxyapi).
Таймауты: OPENAI_CONNECT_TIMEOUT, OPENAI_READ_TIMEOUT (.env).
"""

from __future__ import annotations

import logging
import os

import httpx
from openai import OpenAI

from openai_settings import proxyapi_enabled, require_openai_api_key, resolve_openai_base_url

logger = logging.getLogger(__name__)


def _openai_http_timeout() -> httpx.Timeout:
    connect = float(os.getenv("OPENAI_CONNECT_TIMEOUT", "120"))
    rw = float(os.getenv("OPENAI_READ_TIMEOUT", "180"))
    return httpx.Timeout(connect=connect, read=rw, write=rw, pool=rw)


def create_openai_client() -> OpenAI:
    api_key = require_openai_api_key()
    timeout = _openai_http_timeout()
    base = resolve_openai_base_url()
    if base:
        if proxyapi_enabled():
            logger.info("OpenAI SDK: ProxyAPI (%s)", base)
        return OpenAI(api_key=api_key, base_url=base, timeout=timeout)
    return OpenAI(api_key=api_key, timeout=timeout)
