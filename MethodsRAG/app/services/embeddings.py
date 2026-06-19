import numpy as np
from typing import List, Optional, Tuple

from sentence_transformers import SentenceTransformer

from app.core.config import get_settings
from app.core.logging import logger


settings = get_settings()
_embedding_model: Optional[SentenceTransformer] = None


# -----------------------------------------------------------------------
# Lifecycle
# -----------------------------------------------------------------------

async def load_embedding_model():
    global _embedding_model

    try:
        if _embedding_model is None:
            logger.info("Loading embedding model...")

            try:
                _embedding_model = SentenceTransformer(
                    settings.EMBEDDING_MODEL_NAME
                )
            except Exception as err:
                logger.exception(
                    f"Failed to initialize embedding model: {err}"
                )
                raise

            logger.info("Embedding model loaded.")
    except Exception:
        raise


async def unload_embedding_model():
    global _embedding_model

    try:
        if _embedding_model is not None:
            logger.info("Unloading embedding model...")
            _embedding_model = None
    except Exception as err:
        logger.warning(f"Failed unloading embedding model cleanly: {err}")


def is_embedding_model_loaded() -> bool:
    return _embedding_model is not None


def _ensure_model() -> SentenceTransformer:
    if _embedding_model is None:
        raise RuntimeError(
            "Embedding model not loaded yet. Call load_embedding_model() at startup."
        )
    return _embedding_model


# -----------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    try:
        if not text:
            return ""
        return " ".join(text.strip().split())
    except Exception:
        return ""


def numpy_to_list(v) -> List[float]:
    if v is None:
        return []

    try:
        return np.asarray(v, dtype=np.float32).tolist()
    except Exception:
        try:
            return [float(x) for x in v]
        except Exception:
            return []


# -----------------------------------------------------------------------
# RAW TEXT EMBEDDING — BASELINE (UNCHANGED)
# -----------------------------------------------------------------------

def embed_text(text: str) -> List[float]:
    """
    Encodes raw text using SentenceTransformer

    Used for:
      - Query embedding
      - Individual document fields
    """

    try:
        model = _ensure_model()
    except Exception:
        raise

    try:
        emb = model.encode(
            _normalize_text(text or ""),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    except Exception as err:
        logger.exception(f"Embedding encode failed: {err}")
        return []

    try:
        return numpy_to_list(emb)
    except Exception:
        return []


# -----------------------------------------------------------------------
# METHOD MADL MULTI-VECTOR ENGINE
# -----------------------------------------------------------------------

def embed_method_madl(
    summary: str,
    raw_method: str,
    full_madl_text: str,
) -> Tuple[
    List[float],  # summary_embedding
    List[float],  # raw_method_embedding
    List[float],  # madl_embedding
    List[float],  # main_vector  (summary + method)
]:
    """
    METHOD MADL EMBEDDING STRATEGY

    Computes:

      1. summary_embedding    ← encode(summary)
      2. raw_method_embedding ← encode(raw_method)
      3. madl_embedding       ← encode(full_madl_text)

      4. main_vector          ← encode(summary + " " + raw_method)

    Returns:
        summary_embedding,
        raw_method_embedding,
        madl_embedding,
        main_vector
    """

    # ----------------------------------------------------
    # Normalize Inputs
    # ----------------------------------------------------

    try:
        summary_text = _normalize_text(summary)
    except Exception:
        summary_text = ""

    try:
        method_text = _normalize_text(raw_method)
    except Exception:
        method_text = ""

    try:
        madl_text = _normalize_text(full_madl_text)
    except Exception:
        madl_text = ""


    # ----------------------------------------------------
    # Individual embeddings
    # ----------------------------------------------------

    try:
        summary_emb = embed_text(summary_text)
    except Exception:
        summary_emb = []

    try:
        raw_method_emb = embed_text(method_text)
    except Exception:
        raw_method_emb = []

    try:
        madl_emb = embed_text(madl_text)
    except Exception:
        madl_emb = []


    # ----------------------------------------------------
    # Primary MAIN VECTOR → Summary + Raw Method
    # ----------------------------------------------------

    try:
        combined_text = f"{summary_text} {method_text}".strip()
    except Exception:
        combined_text = ""

    try:
        main_vector = embed_text(combined_text)
    except Exception:
        main_vector = []


    return (
        summary_emb,
        raw_method_emb,
        madl_emb,
        main_vector,
    )
