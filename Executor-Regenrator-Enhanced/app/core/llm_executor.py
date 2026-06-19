"""
LLM Executor - Production Grade

Features:
- Singleton client with bounded concurrency
- API key rotation support
- Role-based token limits from config
- Metrics integration
- Tracing support
- Feature flag support (multimodal)
"""

import asyncio
import logging
import random
from enum import Enum
from typing import Optional, List

from google import genai
from google.genai.types import GenerateContentConfig, GenerateContentResponse, Part

from app.core.config import get_settings
from app.core.metrics import get_metrics
from app.core.tracing import trace, SpanKind

logger = logging.getLogger("llm")


# ==================================================
# Enums
# ==================================================

class LLMRole(str, Enum):
    VERIFIER = "verifier"
    CLASSIFIER = "classifier"
    EXTRACTOR = "extractor"
    MODIFIER = "modifier"


class LLMMode(str, Enum):
    TEXT = "TEXT"
    MULTIMODAL = "MULTIMODAL"
    FALLBACK_TEXT = "FALLBACK_TEXT"


# ==================================================
# LLM Executor
# ==================================================

class LLMExecutor:
    """
    Production-grade LLM executor with:
    - Singleton pattern
    - Bounded concurrency
    - API key rotation
    - Role-based token limits
    - Metrics and tracing
    """

    _instance: Optional["LLMExecutor"] = None
    _semaphore: Optional[asyncio.Semaphore] = None

    # ==================================================
    # LIFECYCLE
    # ==================================================

    @classmethod
    def get_instance(cls, model_name: Optional[str] = None) -> "LLMExecutor":
        if cls._instance is None:
            settings = get_settings()
            cls._instance = cls(model_name=model_name or settings.LLM_MODEL_NAME)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset the singleton (useful for testing)."""
        cls._instance = None
        cls._semaphore = None

    def __init__(self, model_name: str):
        if LLMExecutor._instance is not None:
            raise RuntimeError("LLMExecutor is a singleton - use get_instance()")

        self.settings = get_settings()
        
        # Validate API keys
        if not self.settings.effective_api_keys:
            raise RuntimeError("No Google API key configured")

        self.primary_model = model_name
        self.fallback_model = self.settings.LLM_FALLBACK_MODEL
        self.model_name = model_name
        self._api_keys = list(self.settings.effective_api_keys)
        self._current_key_index = 0
        self._clients: dict[str, genai.Client] = {}
        
        # Initialize semaphore for concurrency control
        if LLMExecutor._semaphore is None:
            LLMExecutor._semaphore = asyncio.Semaphore(
                self.settings.LLM_MAX_CONCURRENT_CALLS
            )
        
        # Initialize primary client
        self._init_client(self._api_keys[0])
        
        LLMExecutor._instance = self

    def _init_client(self, api_key: str) -> genai.Client:
        """Initialize a client for an API key."""
        if api_key not in self._clients:
            self._clients[api_key] = genai.Client(api_key=api_key)
        return self._clients[api_key]

    @property
    def _client(self) -> genai.Client:
        """Get the current client with key rotation support."""
        key = self._api_keys[self._current_key_index]
        return self._init_client(key)

    def _rotate_key(self):
        """Rotate to the next API key."""
        if len(self._api_keys) > 1:
            self._current_key_index = (self._current_key_index + 1) % len(self._api_keys)
            logger.info("Rotated to API key index %d", self._current_key_index)

    # ==================================================
    # TOKEN LIMITS (from config)
    # ==================================================

    def _get_max_tokens(self, role: LLMRole) -> int:
        """Get max tokens for a role from config."""
        token_map = {
            LLMRole.VERIFIER: self.settings.LLM_VERIFIER_MAX_TOKENS,
            LLMRole.CLASSIFIER: self.settings.LLM_CLASSIFIER_MAX_TOKENS,
            LLMRole.EXTRACTOR: self.settings.LLM_EXTRACTOR_MAX_TOKENS,
            LLMRole.MODIFIER: self.settings.LLM_MODIFIER_MAX_TOKENS,
        }
        return token_map.get(role, 128)

    # ==================================================
    # PUBLIC API — TEXT
    # ==================================================

    async def run_verifier(self, prompt: str) -> Optional[str]:
        return await self._run(prompt, LLMRole.VERIFIER, 0)

    async def run_classifier(self, prompt: str) -> Optional[str]:
        return await self._run(prompt, LLMRole.CLASSIFIER, 0)

    async def run_extractor(self, prompt: str) -> Optional[str]:
        return await self._run(prompt, LLMRole.EXTRACTOR, 0)

    async def run_modifier(self, prompt: str) -> Optional[str]:
        return await self._run(prompt, LLMRole.MODIFIER, self.settings.LLM_MAX_RETRIES)

    # --------------------------------------------------
    # STRUCTURED OUTPUT — JSON schema enforced by Gemini
    # --------------------------------------------------

    async def run_verifier_structured(self, prompt: str, schema: type) -> Optional[str]:
        """Run verifier with Gemini structured output — response is guaranteed valid JSON."""
        config = GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )
        return await self._run(prompt, LLMRole.VERIFIER, 0, config)

    async def run_modifier_structured(self, prompt: str, schema: type) -> Optional[str]:
        """Run modifier with Gemini structured output — response is guaranteed valid JSON."""
        config = GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )
        return await self._run(prompt, LLMRole.MODIFIER, self.settings.LLM_MAX_RETRIES, config)

    async def run_multimodal_modifier_structured(
        self, *, prompt: str, image_bytes: bytes, schema: type
    ) -> Optional[str]:
        """Run multimodal modifier with Gemini structured output — response is guaranteed valid JSON."""
        if not self.settings.ENABLE_MULTIMODAL:
            logger.info("Multimodal disabled, falling back to text")
            return await self.run_modifier_structured(prompt, schema)
        config = GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )
        return await self._run_multimodal(
            prompt,
            image_bytes,
            LLMRole.MODIFIER,
            self.settings.LLM_MAX_RETRIES,
            config,
        )

    # ==================================================
    # PUBLIC API — MULTIMODAL
    # ==================================================
    
    async def run_multimodal_modifier(
        self, *, prompt: str, image_bytes: bytes
    ) -> Optional[str]:
        # Check feature flag
        if not self.settings.ENABLE_MULTIMODAL:
            logger.info("Multimodal disabled, falling back to text")
            return await self.run_modifier(prompt)

        return await self._run_multimodal(
            prompt,
            image_bytes,
            LLMRole.MODIFIER,
            self.settings.LLM_MAX_RETRIES,
        )



    async def run_multimodal_classifier(
        self, *, prompt: str, image_bytes: bytes
    ) -> Optional[str]:
        # Check feature flag
        if not self.settings.ENABLE_MULTIMODAL:
            logger.info("Multimodal disabled, falling back to text")
            return await self.run_classifier(prompt)
        
        return await self._run_multimodal(
            prompt, image_bytes, LLMRole.CLASSIFIER, 0
        )

    async def run_multimodal_extractor(
        self, *, prompt: str, image_bytes: bytes
    ) -> Optional[str]:
        # Check feature flag
        if not self.settings.ENABLE_MULTIMODAL:
            logger.info("Multimodal disabled, falling back to text")
            return await self.run_extractor(prompt)
        
        return await self._run_multimodal(
            prompt, image_bytes, LLMRole.EXTRACTOR, 0
        )

    # ==================================================
    # CORE EXECUTION — TEXT
    # ==================================================

    @trace(name="llm.run_text", kind=SpanKind.CLIENT)
    async def _run(
        self,
        prompt: str,
        role: LLMRole,
        retries: int,
        config: Optional[GenerateContentConfig] = None,
    ) -> Optional[str]:

        max_tokens = self._get_max_tokens(role)
        metrics = get_metrics()

        async with self._semaphore:
            for attempt in range(retries + 1):
                try:
                    response = await self._generate_text(prompt, max_tokens, config)
                    self._log_usage(response, role, LLMMode.TEXT)
                    self._record_metrics(role, LLMMode.TEXT, "success", response)
                    text = self._safe_extract_text(response)

                    if text is None:
                        logger.error("LLM RETURNED NO TEXT | RAW RESPONSE = %s", response)

                    return text

                except Exception as exc:
                    exc_str = str(exc).lower()
                    if ("429" in exc_str or "resource_exhausted" in exc_str) and self.model_name == self.primary_model:
                        logger.warning(
                            "LLM %s | Quota exhausted for %s. Switching to %s...",
                            role.value.upper(),
                            self.primary_model,
                            self.fallback_model,
                        )
                        self.model_name = self.fallback_model
                        try:
                            response = await self._generate_text(prompt, max_tokens, config)
                            self._log_usage(response, role, LLMMode.TEXT)
                            self._record_metrics(role, LLMMode.TEXT, "success", response)
                            return self._safe_extract_text(response)
                        except Exception as fallback_exc:
                            exc = fallback_exc

                    self._record_metrics(role, LLMMode.TEXT, "error", error_type=type(exc).__name__)

                    if attempt < retries and self._is_retriable(exc):
                        # Rotate key on rate limit
                        if "429" in str(exc) or "rate" in str(exc).lower():
                            self._rotate_key()

                        await asyncio.sleep(self.settings.LLM_RATE_LIMIT_SLEEP)
                        continue

                    logger.error(
                        "LLM FAILURE | role=%s | attempt=%d | err=%s",
                        role.value, attempt + 1, exc,
                    )
                    return None

    # ==================================================
    # CORE EXECUTION — MULTIMODAL
    # ==================================================

    @trace(name="llm.run_multimodal", kind=SpanKind.CLIENT)
    async def _run_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        role: LLMRole,
        retries: int,
        config: Optional[GenerateContentConfig] = None,
    ) -> Optional[str]:

        if not image_bytes or len(image_bytes) < 12:
            raise ValueError("Invalid or empty image bytes")

        mime_type = self._detect_image_mime_type(image_bytes)
        if not mime_type:
            raise ValueError("Unsupported image format")

        max_tokens = self._get_max_tokens(role)
        metrics = get_metrics()

        async with self._semaphore:
            for attempt in range(retries + 1):
                try:
                    response = await self._generate_multimodal(
                        prompt, image_bytes, max_tokens, mime_type, config
                    )
                    self._log_usage(response, role, LLMMode.MULTIMODAL)
                    self._record_metrics(role, LLMMode.MULTIMODAL, "success", response)
                    text = self._safe_extract_text(response)

                    if text is None:
                        logger.error("LLM MULTIMODAL RETURNED NO TEXT | RAW RESPONSE = %s", response)

                    return text

                except Exception as exc:
                    exc_str = str(exc).lower()
                    if ("429" in exc_str or "resource_exhausted" in exc_str) and self.model_name == self.primary_model:
                        logger.warning(
                            "LLM %s | Quota exhausted for %s. Switching to %s...",
                            role.value.upper(),
                            self.primary_model,
                            self.fallback_model,
                        )
                        self.model_name = self.fallback_model
                        try:
                            response = await self._generate_multimodal(
                                prompt, image_bytes, max_tokens, mime_type, config
                            )
                            self._log_usage(response, role, LLMMode.MULTIMODAL)
                            self._record_metrics(role, LLMMode.MULTIMODAL, "success", response)
                            return self._safe_extract_text(response)
                        except Exception as fallback_exc:
                            exc = fallback_exc

                    msg = str(exc).lower()

                    # --------------------------------------------------
                    # MODEL-LEVEL IMAGE REJECTION -> FALLBACK
                    # --------------------------------------------------
                    if any(k in msg for k in (
                        "unsupported image",
                        "image too large",
                        "invalid image format",
                        "not a valid png",
                        "image exceeds",
                    )):
                        logger.warning(
                            "LLM %s | MODE=MULTIMODAL_FAILED -> FALLBACK_TEXT",
                            role.value.upper(),
                        )
                        self._record_metrics(role, LLMMode.MULTIMODAL, "fallback")
                        return await self._run(prompt, role, 0, config)

                    # --------------------------------------------------
                    # RETRIABLE TRANSIENT ERRORS
                    # --------------------------------------------------
                    if attempt < retries and self._is_retriable(exc):
                        if "429" in str(exc) or "rate" in str(exc).lower():
                            self._rotate_key()

                        await asyncio.sleep(self.settings.LLM_RATE_LIMIT_SLEEP)
                        continue

                    # --------------------------------------------------
                    # SDK / DEVELOPER ERRORS - DO NOT SWALLOW
                    # --------------------------------------------------
                    self._record_metrics(role, LLMMode.MULTIMODAL, "error", error_type=type(exc).__name__)
                    logger.error(
                        "LLM MULTIMODAL HARD FAILURE | role=%s | err=%s",
                        role.value, exc,
                    )
                    raise

    # ==================================================
    # GENERATORS
    # ==================================================

    async def _generate_text(
        self,
        prompt: str,
        max_tokens: int,
        config: Optional[GenerateContentConfig] = None,
    ):
        loop = asyncio.get_running_loop()
        # Omit max_output_tokens to prevent the SDK/API truncation bug
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: self._client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                ),
            ),
            timeout=self.settings.LLM_TIMEOUT_SECONDS,
        )

    async def _generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        max_tokens: int,
        mime_type: str,
        config: Optional[GenerateContentConfig] = None,
    ):
        contents = [
            prompt,
            Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type,
            ),
        ]

        loop = asyncio.get_running_loop()
        # Omit max_output_tokens to prevent the SDK/API truncation bug
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: self._client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                ),
            ),
            timeout=self.settings.LLM_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _detect_image_mime_type(image_bytes: bytes) -> Optional[str]:
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if image_bytes[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return None

    # ==================================================
    # HELPERS
    # ==================================================

    @staticmethod
    def _safe_extract_text(
        response: GenerateContentResponse,
    ) -> Optional[str]:
        try:
            # 1. Try standard parts
            for cand in response.candidates:
                content = getattr(cand, "content", None)
                if not content:
                    continue

                parts = getattr(content, "parts", [])
                for part in parts:
                    text = getattr(part, "text", None)
                    if text:
                        return text.strip()

            # 2. Try response.text (some SDK versions expose this)
            text = getattr(response, "text", None)
            if text:
                return text.strip()

            # 3. Try stringifying
            s = str(response)
            if s:
                return s

        except Exception as e:
            logger.error("LLM TEXT EXTRACTION FAILED | err=%s", e)

        return None


    @staticmethod
    def _is_retriable(exc: Exception) -> bool:
        return any(
            k in str(exc).lower()
            for k in ("rate", "timeout", "429", "503", "500")
        )

    def _log_usage(self, response, role: LLMRole, mode: LLMMode):
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", 0)
        completion_tokens = getattr(usage, "candidates_token_count", 0)
        
        logger.info(
            "LLM %s | MODE=%s | model=%s | prompt_tokens=%s | completion_tokens=%s",
            role.value.upper(),
            mode.value,
            self.model_name,
            prompt_tokens,
            completion_tokens,
        )

    def _record_metrics(
        self,
        role: LLMRole,
        mode: LLMMode,
        status: str,
        response: Optional[GenerateContentResponse] = None,
        error_type: Optional[str] = None,
    ):
        """Record LLM call metrics."""
        try:
            metrics = get_metrics()
            
            # Count calls
            metrics.llm_calls_total.inc(
                role=role.value,
                mode=mode.value,
                status=status,
            )
            
            # Count tokens if available
            if response:
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    prompt_tokens = getattr(usage, "prompt_token_count", 0)
                    completion_tokens = getattr(usage, "candidates_token_count", 0)
                    
                    if prompt_tokens:
                        metrics.llm_tokens_total.inc(
                            prompt_tokens,
                            role=role.value,
                            type="prompt",
                        )
                    if completion_tokens:
                        metrics.llm_tokens_total.inc(
                            completion_tokens,
                            role=role.value,
                            type="completion",
                        )
            
            # Count errors
            if error_type:
                metrics.llm_errors_total.inc(
                    role=role.value,
                    error_type=error_type,
                )
        except Exception:
            # Don't let metrics failures affect LLM operations
            pass
