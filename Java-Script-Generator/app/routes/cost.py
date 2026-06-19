# app/routes/cost.py
"""
Cost Estimation API Routes

Production-ready implementation with:
- Validation
- Structured logging
- Defensive error handling
- Typed responses
- Provider/model verification
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from enum import Enum
import logging

from app.models.test_case import TestCase
from app.core.cost_estimator import estimate_cost, get_pricing
from app.core.config import get_settings

router = APIRouter()
logger = logging.getLogger("api.cost")


# ==============================
# ENUMS
# ==============================

class ConfidenceLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# ==============================
# REQUEST / RESPONSE MODELS
# ==============================

class CostEstimateRequest(BaseModel):
    """Request for cost estimation."""
    test_case: TestCase
    provider: Optional[str] = Field(
        default=None,
        description="LLM provider override"
    )
    model: Optional[str] = Field(
        default=None,
        description="Model override"
    )


class CostEstimateResponse(BaseModel):
    """Cost estimation response."""
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_llm_calls: int
    estimated_cost_usd: float
    cost_breakdown: Dict[str, float]
    confidence: ConfidenceLevel
    warnings: List[str]
    provider: str
    model: str


# ==============================
# ROUTES
# ==============================

@router.post(
    "/estimate",
    response_model=CostEstimateResponse,
    summary="Estimate generation cost",
    description="Estimate token usage and cost for a test case before processing.",
)
async def get_cost_estimate(request: CostEstimateRequest):
    """
    Estimate the cost of generating a test script.
    """

    settings = get_settings()

    provider = request.provider or settings.LLM_PROVIDER
    model = request.model or settings.PRIMARY_MODEL

    # Validate provider + model
    pricing = get_pricing()

    if provider not in pricing:
        logger.warning("Unsupported provider requested: %s", provider)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider: {provider}"
        )

    if model not in pricing[provider]:
        logger.warning(
            "Unsupported model requested: provider=%s model=%s",
            provider,
            model
        )
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model '{model}' for provider '{provider}'"
        )

    # Estimate cost safely
    try:
        estimate = estimate_cost(
            description=request.test_case.description,
            steps=request.test_case.steps,
            prerequisites=request.test_case.prerequisites,
            provider=provider,
            model=model,
        )
    except ValueError as e:
        logger.warning(
            "Cost estimation validation error",
            extra={"error": str(e)}
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Unexpected error during cost estimation")
        raise HTTPException(
            status_code=500,
            detail="Internal cost estimation error"
        )

    # Structured logging (observability friendly)
    logger.info(
        "cost_estimate",
        extra={
            "test_case_id": request.test_case.test_case_id,
            "provider": provider,
            "model": model,
            "tokens": estimate.estimated_total_tokens,
            "cost_usd": estimate.estimated_cost_usd,
            "llm_calls": estimate.estimated_llm_calls,
        },
    )

    return CostEstimateResponse(
        **estimate.to_dict(),
        provider=provider,
        model=model,
    )


@router.get(
    "/pricing",
    summary="Get current pricing",
    description="Get current token pricing for all supported providers and models.",
)
async def get_current_pricing():
    """
    Get current LLM pricing information.
    """

    try:
        pricing = get_pricing()

        return {
            "pricing": {
                provider: {
                    model: {
                        "input_price_per_1m_tokens": model_data.input_price,
                        "output_price_per_1m_tokens": model_data.output_price,
                    }
                    for model, model_data in models.items()
                }
                for provider, models in pricing.items()
            },
            "note": "Prices are in USD per 1 million tokens",
        }

    except Exception:
        logger.exception("Failed to retrieve pricing information")
        raise HTTPException(
            status_code=500,
            detail="Unable to fetch pricing information"
        )
