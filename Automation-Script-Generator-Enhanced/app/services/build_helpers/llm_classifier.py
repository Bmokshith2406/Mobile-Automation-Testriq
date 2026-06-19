# app/services/llm_classifier.py
"""
LLM-Based Action Classifier

Classifies test step intents into action types using LLM.
"""

from typing import Optional, Tuple
import logging
import re

from app.core.llm_json import generate_json
from app.core.config import get_settings
from app.core.json_schemas import CLASSIFICATION_SCHEMA
from app.models.cir import ActionType
from app.prompts.templates import PromptTemplates

logger = logging.getLogger("llm_action_classifier")
settings = get_settings()


class LLMActionClassifier:
    """
    Pure LLM-based action classifier with confidence and retry.
    
    Uses centralized configuration and prompt templates.
    """
    
    ALLOWED_LABELS = {
        "navigate": ActionType.navigate,
        "click": ActionType.click,
        "type": ActionType.type,
        "select": ActionType.select,
        "assert": ActionType.assert_action,
    }
    
    def __init__(self):
        self.min_confidence = settings.MIN_CONFIDENCE_THRESHOLD
        self.max_retries = settings.MAX_EXTRACTOR_RETRIES
    
    async def classify(
        self,
        intent: str,
        expected_outcome: Optional[str] = None,
        matched_script: Optional[str] = None,
    ) -> ActionType:
        result, _ = await self.classify_with_confidence(
            intent=intent,
            expected_outcome=expected_outcome,
            matched_script=matched_script,
        )
        return result
    
    async def classify_with_confidence(
        self,
        intent: str,
        expected_outcome: Optional[str] = None,
        matched_script: Optional[str] = None,
        *,
        use_cache: bool = True,
    ) -> Tuple[ActionType, Optional[int]]:
        if not intent or not intent.strip():
            return ActionType.assert_action, None

        last_label = None

        for attempt in range(self.max_retries + 1):
            prompt = PromptTemplates.classification(
                intent=intent,
                expected=expected_outcome,
                script=matched_script,
            )

            try:
                # First attempt can use cache, retries must be fresh
                attempt_cache = use_cache and attempt == 0

                data = await generate_json(
                    prompt,
                    purpose="action_classification",
                    use_cache=attempt_cache,
                    schema=CLASSIFICATION_SCHEMA,
                )
            except Exception as exc:
                logger.error("Classification LLM error | attempt=%d | error=%s", attempt, exc)
                continue

            label, confidence = self._parse_response(data)
            last_label = label

            if label is None:
                logger.debug("Invalid label from LLM, retrying | attempt=%d", attempt)
                continue

            if confidence is None:
                logger.debug("Missing confidence from LLM, retrying | attempt=%d", attempt)
                continue

            if confidence < self.min_confidence:
                logger.debug(
                    "Low confidence %d < %d, retrying | attempt=%d",
                    confidence,
                    self.min_confidence,
                    attempt,
                )
                continue

            return self.ALLOWED_LABELS[label], confidence

        logger.warning("Classification failed after retries | last_label=%r", last_label)
        return ActionType.assert_action, None

    
    def _parse_response(self, data) -> Tuple[Optional[str], Optional[int]]:
        if not isinstance(data, dict):
            return None, None
        
        # Support both "action" and "action_type" keys
        raw_label = data.get("action") or data.get("action_type")
        raw_confidence = data.get("confidence")
        
        label = self._normalize_label(raw_label)
        confidence = self._normalize_confidence(raw_confidence)
        
        if label not in self.ALLOWED_LABELS:
            return None, confidence
        
        return label, confidence
    
    def _normalize_label(self, raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        
        raw_str = str(raw).lower().strip().split()[0]
        if raw_str.startswith("actiontype."):
            raw_str = raw_str.replace("actiontype.", "")
            
        label = re.sub(
            r"[^a-z]",
            "",
            raw_str,
        )
        
        # Handle common variations
        if label in ("navigation", "nav", "goto"):
            return "navigate"
        if label in ("assertion", "verify", "validation", "expect"):
            return "assert"
        if label in ("typing", "input", "fill", "enter"):
            return "type"
        if label in ("choosing", "dropdown", "pick"):
            return "select"
        
        return label
    
    def _normalize_confidence(self, raw) -> Optional[int]:
        try:
            c = int(raw)
        except Exception:
            return None
        
        if 0 <= c <= 100:
            return c
        
        return None

