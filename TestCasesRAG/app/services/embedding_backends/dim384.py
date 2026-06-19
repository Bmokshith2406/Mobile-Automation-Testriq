from app.services.embedding_backends.base import EmbeddingBackendSpec


BACKEND = EmbeddingBackendSpec(
    preset="minilm_384",
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    dimensions=384,
)
