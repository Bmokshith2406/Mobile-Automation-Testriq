# app/core/cost_estimator.py
"""
Cost Estimation System

Estimates token usage and costs before running generation.
"""

import re
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import logging

from app.core.config import get_settings

logger = logging.getLogger("cost_estimator")

class LLMProvider(str, Enum):
    """Supported LLM providers."""
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass
class TokenPricing:
    """Token pricing per 1M tokens."""
    input_price: float  # USD per 1M input tokens
    output_price: float  # USD per 1M output tokens


# Pricing data (as of 2024, update as needed)
PRICING: Dict[str, Dict[str, TokenPricing]] = {
    "gemini": {
        "gemini-2.5-pro": TokenPricing(input_price=1.25, output_price=5.00),
        "gemini-2.0-flash": TokenPricing(input_price=0.075, output_price=0.30),
        "gemini-1.5-pro": TokenPricing(input_price=1.25, output_price=5.00),
        "gemini-1.5-flash": TokenPricing(input_price=0.075, output_price=0.30),
    },
    "openai": {
        "gpt-4o": TokenPricing(input_price=2.50, output_price=10.00),
        "gpt-4o-mini": TokenPricing(input_price=0.15, output_price=0.60),
        "gpt-4-turbo": TokenPricing(input_price=10.00, output_price=30.00),
        "gpt-3.5-turbo": TokenPricing(input_price=0.50, output_price=1.50),
    },
    "anthropic": {
        "claude-3-opus": TokenPricing(input_price=15.00, output_price=75.00),
        "claude-3-sonnet": TokenPricing(input_price=3.00, output_price=15.00),
        "claude-3-haiku": TokenPricing(input_price=0.25, output_price=1.25),
    },
}


@dataclass
class CostEstimate:
    """Cost estimation result."""
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_llm_calls: int
    estimated_cost_usd: float
    cost_breakdown: Dict[str, float]
    confidence: str  # "high", "medium", "low"
    warnings: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "estimated_total_tokens": self.estimated_total_tokens,
            "estimated_llm_calls": self.estimated_llm_calls,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "cost_breakdown": {k: round(v, 6) for k, v in self.cost_breakdown.items()},
            "confidence": self.confidence,
            "warnings": self.warnings,
        }


class CostEstimator:
    """
    Estimates costs for test case generation.
    
    Uses heuristics based on test case complexity to estimate:
    - Number of LLM calls
    - Token counts
    - Total cost
    """
    
    # Average tokens per operation type
    TOKENS_PER_OPERATION = {
        "classification": {"input": 500, "output": 50},
        "type_extraction": {"input": 800, "output": 200},
        "click_extraction": {"input": 600, "output": 150},
        "select_extraction": {"input": 700, "output": 180},
        "assert_extraction": {"input": 900, "output": 250},
        "verification": {"input": 1200, "output": 300},
        "code_generation": {"input": 1500, "output": 800},
    }
    
    # Complexity multipliers
    COMPLEXITY_MULTIPLIERS = {
        "simple": 0.8,
        "medium": 1.0,
        "complex": 1.3,
        "very_complex": 1.6,
    }
    
    def __init__(
        self,
        provider: str = None,
        model: str = None,
    ):
        settings = get_settings()
        self.provider = provider or settings.LLM_PROVIDER
        self.model = model or settings.PRIMARY_MODEL
    
    def _get_pricing(self) -> TokenPricing:
        """Get pricing for current provider/model."""
        provider_pricing = PRICING.get(self.provider, {})
        model_pricing = provider_pricing.get(self.model)
        
        if not model_pricing:
            # Default to medium pricing
            logger.warning(
                "Pricing not found for %s/%s, using default",
                self.provider, self.model,
            )
            return TokenPricing(input_price=1.0, output_price=3.0)
        
        return model_pricing
    
    def _estimate_complexity(self, description: str, steps: List[Any]) -> str:
        """Estimate test case complexity."""
        # Factors that increase complexity
        complexity_score = 0
        
        # Number of steps
        num_steps = len(steps)
        if num_steps <= 3:
            complexity_score += 1
        elif num_steps <= 7:
            complexity_score += 2
        elif num_steps <= 15:
            complexity_score += 3
        else:
            complexity_score += 4
        
        # Check for complex operations in descriptions
        all_text = description.lower()
        for step in steps:
            step_desc = getattr(step, "description", str(step)).lower()
            all_text += " " + step_desc
        
        complex_patterns = [
            r"(verify|assert|validate|check|ensure)",
            r"(dropdown|select|combo)",
            r"(table|grid|list)",
            r"(modal|dialog|popup)",
            r"(upload|download|file)",
            r"(drag|drop|resize)",
            r"(scroll|infinite)",
            r"(wait|timeout|delay)",
        ]
        
        for pattern in complex_patterns:
            if re.search(pattern, all_text):
                complexity_score += 0.5
        
        # Map score to complexity level
        if complexity_score <= 2:
            return "simple"
        elif complexity_score <= 4:
            return "medium"
        elif complexity_score <= 6:
            return "complex"
        else:
            return "very_complex"
    
    def _count_operations(self, steps: List[Any]) -> Dict[str, int]:
        """Count expected LLM operations per step."""
        operations = {
            "classification": 0,
            "type_extraction": 0,
            "click_extraction": 0,
            "select_extraction": 0,
            "assert_extraction": 0,
            "verification": 0,
            "code_generation": 0,
        }
        
        for step in steps:
            desc = getattr(step, "description", str(step)).lower()
            
            # Always classify
            operations["classification"] += 1
            
            # Estimate operation types based on keywords
            if any(kw in desc for kw in ["type", "enter", "input", "fill"]):
                operations["type_extraction"] += 1
            
            if any(kw in desc for kw in ["click", "press", "tap", "button"]):
                operations["click_extraction"] += 1
            
            if any(kw in desc for kw in ["select", "dropdown", "choose", "option"]):
                operations["select_extraction"] += 1
            
            if any(kw in desc for kw in ["verify", "assert", "check", "ensure", "see"]):
                operations["assert_extraction"] += 1
            
            # Verification happens for complex steps
            if len(desc) > 50 or any(kw in desc for kw in ["then", "should", "must"]):
                operations["verification"] += 1
        
        # Code generation is per test case
        operations["code_generation"] = 1
        
        return operations
    
    def estimate(
        self,
        description: str,
        steps: List[Any],
        prerequisites: List[Any] = None,
    ) -> CostEstimate:
        """
        Estimate cost for generating a test script.
        
        Args:
            description: Test case description
            steps: List of test steps
            prerequisites: Optional list of prerequisites
            
        Returns:
            CostEstimate with detailed breakdown
        """
        warnings = []
        
        # Include prerequisites in step count
        all_steps = list(steps)
        if prerequisites:
            all_steps.extend(prerequisites)
        
        # Estimate complexity
        complexity = self._estimate_complexity(description, all_steps)
        multiplier = self.COMPLEXITY_MULTIPLIERS[complexity]
        
        # Count operations
        operations = self._count_operations(all_steps)
        
        # Calculate tokens
        total_input_tokens = 0
        total_output_tokens = 0
        cost_breakdown = {}
        
        for op_type, count in operations.items():
            if count > 0:
                base_tokens = self.TOKENS_PER_OPERATION[op_type]
                input_tokens = int(base_tokens["input"] * count * multiplier)
                output_tokens = int(base_tokens["output"] * count * multiplier)
                
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                
                # Calculate cost for this operation type
                pricing = self._get_pricing()
                op_cost = (
                    (input_tokens / 1_000_000) * pricing.input_price +
                    (output_tokens / 1_000_000) * pricing.output_price
                )
                cost_breakdown[op_type] = op_cost
        
        # Total LLM calls
        total_llm_calls = sum(operations.values())
        
        # Total cost
        pricing = self._get_pricing()
        total_cost = (
            (total_input_tokens / 1_000_000) * pricing.input_price +
            (total_output_tokens / 1_000_000) * pricing.output_price
        )
        
        # Determine confidence
        if len(all_steps) <= 5:
            confidence = "high"
        elif len(all_steps) <= 15:
            confidence = "medium"
        else:
            confidence = "low"
            warnings.append("Large test case - estimate may vary significantly")
        
        # Add warnings for complex scenarios
        if complexity == "very_complex":
            warnings.append("Complex test case detected - actual cost may be higher")
        
        if total_llm_calls > 20:
            warnings.append(f"High number of LLM calls ({total_llm_calls}) - consider breaking into smaller tests")
        
        return CostEstimate(
            estimated_input_tokens=total_input_tokens,
            estimated_output_tokens=total_output_tokens,
            estimated_total_tokens=total_input_tokens + total_output_tokens,
            estimated_llm_calls=total_llm_calls,
            estimated_cost_usd=total_cost,
            cost_breakdown=cost_breakdown,
            confidence=confidence,
            warnings=warnings,
        )


# Convenience function
def estimate_cost(
    description: str,
    steps: List[Any],
    prerequisites: List[Any] = None,
    provider: str = None,
    model: str = None,
) -> CostEstimate:
    """Estimate cost for a test case."""
    estimator = CostEstimator(provider=provider, model=model)
    return estimator.estimate(description, steps, prerequisites)

# ==========================================
# PRICING ACCESSOR
# ==========================================

def get_pricing() -> Dict[str, Dict[str, TokenPricing]]:
    """
    Return current pricing configuration.

    Exposed as a function instead of importing PRICING directly
    to improve testability and abstraction.
    """
    return PRICING

