from app.services.embedding_backends.base import EmbeddingBackendSpec


BACKEND = EmbeddingBackendSpec(
    preset="bge_large_1024",
    model_name="BAAI/bge-large-en-v1.5",
    dimensions=1024,
)
