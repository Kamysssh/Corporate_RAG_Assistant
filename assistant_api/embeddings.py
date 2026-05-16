"""
Эмбеддинги для RAG и семантического кеша.

- openai: OpenAI Embeddings API (или OPENAI_BASE_URL в openai_client).
- local: sentence-transformers без запросов к Embeddings API (при ошибке 403 region).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from config import EMBEDDING_MODEL, LOCAL_EMBEDDING_MODEL, get_embeddings_backend

if TYPE_CHECKING:
    from openai import OpenAI

logger = logging.getLogger(__name__)

_local_model = None


def _get_sentence_model():
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("Локальные эмбеддинги: загрузка %s", LOCAL_EMBEDDING_MODEL)
        _local_model = SentenceTransformer(LOCAL_EMBEDDING_MODEL)
    return _local_model


def _embed_local(text: str) -> list[float]:
    model = _get_sentence_model()
    v = model.encode(
        text[:8000],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return np.asarray(v, dtype=np.float64).tolist()


def embed_text(text: str, openai_client: "OpenAI | None" = None) -> list[float]:
    if not text or not str(text).strip():
        raise ValueError("Пустой текст для embedding")

    if get_embeddings_backend() == "local":
        return _embed_local(text)

    if openai_client is None:
        from openai_client import create_openai_client

        openai_client = create_openai_client()

    try:
        response = openai_client.embeddings.create(
            input=text[:8000],
            model=EMBEDDING_MODEL,
        )
        return list(response.data[0].embedding)
    except Exception as exc:
        err = str(exc).lower()
        if (
            "unsupported_country" in err
            or "country, region, or territory not supported" in err
            or "403" in err
        ):
            raise RuntimeError(
                "OpenAI Embeddings недоступен из вашего региона (403). "
                "На VPS укажите ProxyAPI: OPENAI_API_PROVIDER=proxyapi и PROXYAPI_KEY в .env, "
                "либо EMBEDDINGS_BACKEND=local и заново выполните переиндексацию "
                "(python reindex.py --role all)."
            ) from exc
        raise
