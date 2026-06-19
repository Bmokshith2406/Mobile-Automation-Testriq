from __future__ import annotations

from app.core.config import get_settings, resolve_embedding_preset
from app.services.embedding_backends.base import EmbeddingBackendSpec
from app.services.embedding_backends.dim1024 import BACKEND as BACKEND_1024
from app.services.embedding_backends.dim384 import BACKEND as BACKEND_384
from app.services.embedding_backends.dim768 import BACKEND as BACKEND_768


EMBEDDING_BACKENDS = {
    BACKEND_384.preset: BACKEND_384,
    BACKEND_768.preset: BACKEND_768,
    BACKEND_1024.preset: BACKEND_1024,
}


def get_embedding_backend(settings=None) -> EmbeddingBackendSpec:
    current = settings or get_settings()
    preset = resolve_embedding_preset(current)
    backend = EMBEDDING_BACKENDS.get(preset or "")
    if backend is not None:
        return backend

    configured_model = (current.EMBEDDING_MODEL_NAME or "").strip()
    if configured_model:
        return EmbeddingBackendSpec(
            preset="custom",
            model_name=configured_model,
            dimensions=int(current.EMBEDDING_DIMENSIONS),
        )

    return BACKEND_384


__all__ = [
    "EmbeddingBackendSpec",
    "EMBEDDING_BACKENDS",
    "get_embedding_backend",
]
