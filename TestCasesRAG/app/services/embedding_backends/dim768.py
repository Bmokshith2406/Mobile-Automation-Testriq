from app.services.embedding_backends.base import EmbeddingBackendSpec


BACKEND = EmbeddingBackendSpec(
    preset="mpnet_768",
    model_name="sentence-transformers/all-mpnet-base-v2",
    dimensions=768,
)
