import re
from typing import List, Dict, Any

import numpy as np

from app.core.config import get_settings
from app.core.logging import logger
from app.services.rerank import rerank_with_gemini

settings = get_settings()


# -----------------------------------------------------
# TRUE Cosine similarity
# -----------------------------------------------------
def _cosine_sim(a, b) -> float:

    try:
        a_arr = np.asarray(a, dtype=np.float32)
        b_arr = np.asarray(b, dtype=np.float32)

        if a_arr.size == 0 or b_arr.size == 0:
            return 0.0

        denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)

        if denom == 0:
            return 0.0

        return float(np.dot(a_arr, b_arr) / denom)

    except Exception:
        return 0.0


# -----------------------------------------------------
# Tokenizer — lexical intent booster
# -----------------------------------------------------
def _tokenize(text: str):

    try:
        if not text or not isinstance(text, str):
            return set()

        return set(re.findall(r"\b[\w\-']+\b", text.lower()))

    except Exception:
        return set()


# -----------------------------------------------------
# Candidate generation & scoring
# -----------------------------------------------------
def build_candidates(
    raw_query: str,
    all_expansions: List[str],
    query_vector: List[float],
    search_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    try:
        expansion_tokens = set()

        for ex in all_expansions or []:
            expansion_tokens.update(_tokenize(ex))

    except Exception:
        expansion_tokens = set()

    candidates: List[Dict[str, Any]] = []

    for res in search_results or []:

        try:
            payload = res.get("document", {}) or {}
        except Exception:
            payload = {}

        try:
            base_score = float(res.get("score", 0.0) or 0.0)
        except Exception:
            base_score = 0.0

        # -------------------------------------------------
        # Semantic similarity
        # -------------------------------------------------

        try:
            main_emb = payload.get("main_vector", [])
            summary_emb = payload.get("summary_embedding", [])
        except Exception:
            main_emb, summary_emb = [], []

        sim_main = _cosine_sim(query_vector, main_emb)
        sim_summary = _cosine_sim(query_vector, summary_emb)

        try:
            semantic_max = max(sim_main, sim_summary)
        except Exception:
            semantic_max = 0.0

        # -------------------------------------------------
        # Lexical boosts
        # -------------------------------------------------

        try:
            keywords = [
                str(k).lower()
                for k in payload
                .get("method_documentation", {})
                .get("keywords", [])
            ]
        except Exception:
            keywords = []

        try:
            text_fields = (
                f'{payload.get("method_name","")} '
                f'{payload.get("raw_method_code","")} '
                f'{payload.get("method_documentation", {}).get("summary","")}'
            ).lower()
        except Exception:
            text_fields = ""

        text_tokens = _tokenize(text_fields)

        token_boost = 0.0

        for tok in expansion_tokens:

            try:
                if tok in text_tokens:
                    token_boost += 0.10

                if tok in keywords:
                    token_boost += 0.15

            except Exception:
                continue

        try:
            max_boost = max(len(expansion_tokens), 1)
            token_boost = min(token_boost, max_boost * 0.15)
        except Exception:
            pass

        # -------------------------------------------------
        # Score Variant A
        # -------------------------------------------------

        try:
            score_v1 = (
                0.60 * base_score +
                0.25 * semantic_max +
                token_boost
            )
        except Exception:
            score_v1 = 0.0

        # -------------------------------------------------
        # Score Variant B
        # -------------------------------------------------

        try:
            popularity = float(
                payload.get("popularity", payload.get("Popularity", 0.0)) or 0.0
            )
        except Exception:
            popularity = 0.0

        popularity_boost = min(popularity / 100.0, 0.10)

        keyword_overlap = len(
            [k for k in keywords if k in expansion_tokens]
        )

        try:
            score_v2 = (
                0.45 * base_score
                + 0.20 * semantic_max
                + 0.12 * min(keyword_overlap, 5) / 5.0
                + 0.05 * token_boost
                + 0.05 * popularity_boost
            )
        except Exception:
            score_v2 = 0.0

        try:

            candidates.append(
                {
                    "_id": payload.get("_id") or payload.get("id"),
                    "raw_score": base_score,
                    "local_score_v1": float(score_v1),
                    "local_score_v2": float(score_v2),
                    "method_name": payload.get("method_name", "N/A"),
                    "summary": payload.get("method_documentation", {}).get("summary", ""),
                    "keywords": keywords,
                    "payload": payload,
                }
            )

        except Exception as err:
            logger.warning(f"Failed building method candidate: {err}")

    return candidates


# -----------------------------------------------------
# Score normalization
# -----------------------------------------------------
def _normalize_scores(
    candidates: List[Dict[str, Any]],
    key: str,
):

    try:

        if not candidates:
            return

        scores = np.array(
            [c[key] for c in candidates],
            dtype=np.float32,
        )

        min_s = float(scores.min())
        max_s = float(scores.max())

        if max_s - min_s > 1e-12:

            for c in candidates:
                c["local_score_norm"] = (
                    (c[key] - min_s) / (max_s - min_s)
                )

        else:

            for c in candidates:
                c["local_score_norm"] = 1.0

    except Exception:
        return


# -----------------------------------------------------
# Final Selection
# -----------------------------------------------------
async def select_final_results(
    raw_query: str,
    candidates: List[Dict[str, Any]],
    ranking_variant: str = "A",
    use_gemini_rerank: bool = True,
    final_results: int = 3,
    **_,
) -> List[Dict[str, Any]]:

    try:

        if not candidates:
            return []

        score_key = (
            "local_score_v1"
            if ranking_variant.upper() == "A"
            else "local_score_v2"
        )

        _normalize_scores(candidates, score_key)

        candidates.sort(
            key=lambda x: x.get(score_key, 0.0),
            reverse=True,
        )

        top_candidates = candidates[
            : settings.CANDIDATES_TO_RETRIEVE
        ]

        if use_gemini_rerank:

            try:
                reranked = await rerank_with_gemini(
                    raw_query,
                    top_candidates,
                )

                return reranked[:final_results]

            except Exception as e:
                logger.warning(f"Gemini rerank failed: {e}")

        return top_candidates[:final_results]

    except Exception:
        return []
