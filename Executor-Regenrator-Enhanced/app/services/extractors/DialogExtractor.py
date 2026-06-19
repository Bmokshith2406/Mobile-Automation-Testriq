from typing import Optional
import re
import logging

from app.core.llm_executor import LLMExecutor
from app.models.extraction import ExtractedLocator
from app.core.dom_pruner import DomPruner
from app.core.prompts import build_dialog_extractor_prompt
from app.models.cir import DialogAction, LocatorStrategy
from app.services.extractors.BaseExtractor import BaseExtractor

logger = logging.getLogger("dialog_extractor")


class DialogActionExtractor(BaseExtractor):
    """
    Runtime dialog / popup evidence extractor.
    """

    async def extract(
        self,
        *,
        step_intent: str,
        original_code: str,
        error_message: str,
        dom_snapshot: Optional[str],
        error_image_bytes: Optional[bytes] = None,
        framework: str = "playwright",
    ) -> Optional[tuple[DialogAction, Optional[ExtractedLocator]]]:

        logger.debug(
            "DIALOG EXTRACT | intent=%r | error=%r",
            step_intent,
            error_message,
        )

        self._last_step_intent = step_intent
        self._last_original_code = original_code
        self._last_dom_snapshot = dom_snapshot

        llm_hint = await self._ask_llm(
            step_intent=step_intent,
            original_code=original_code,
            error_message=error_message,
            dom_snapshot=dom_snapshot,
            error_image_bytes=error_image_bytes,
            framework=framework,
        )

        if not llm_hint:
            logger.debug("DIALOG EXTRACT | LLM returned none")
            return None

        if isinstance(llm_hint, str):
            lines = [ln.strip() for ln in llm_hint.splitlines() if ln.strip()]
            llm_hint = lines[0] if lines else None

        if not llm_hint:
            logger.debug("DIALOG EXTRACT | LLM returned only empty lines")
            return None

        result = self._normalize_llm_hint(llm_hint)

        if not result:
            logger.warning(
                "DIALOG EXTRACT | discarded LLM hint: %r",
                llm_hint,
            )
            return None

        return result

    async def _ask_llm(
        self,
        *,
        step_intent: str,
        original_code: str,
        error_message: str,
        dom_snapshot: Optional[str],
        error_image_bytes: Optional[bytes],
        framework: str,
    ) -> Optional[str]:

        keyword = None

        if error_message:
            m = re.search(r"'([^']+)'", error_message)
            if m:
                keyword = m.group(1)

        if not keyword:
            m = re.search(r"'([^']+)'", step_intent or "")
            if m:
                keyword = m.group(1)

        pruned_dom = DomPruner.prune(dom_snapshot, keyword, framework=framework)
        self._last_dom_snapshot = pruned_dom or ""

        prompt = build_dialog_extractor_prompt(
            step_intent=step_intent,
            original_code=original_code,
            error_message=error_message,
            dom_snapshot=pruned_dom,
            framework=framework,
        )

        executor = LLMExecutor.get_instance()

        if error_image_bytes:
            return await executor.run_multimodal_extractor(
                prompt=prompt,
                image_bytes=error_image_bytes,
            )

        return await executor.run_extractor(prompt=prompt)

    def _normalize_llm_hint(
        self,
        text: str,
    ) -> Optional[tuple[DialogAction, Optional[ExtractedLocator]]]:

        if not isinstance(text, str):
            return None

        raw = text.strip()

        if not raw:
            return None

        if raw.lower() == "none":
            return None

        match = re.match(
            r"dialog:(accept|dismiss|close):(.*)",
            raw,
            flags=re.IGNORECASE,
        )
        if not match:
            return None

        action_str = match.group(1).lower()
        try:
            action = DialogAction(action_str)
        except Exception:
            logger.warning("DIALOG EXTRACT | unknown action: %s", action_str)
            return None

        locator_raw = match.group(2).strip()

        if locator_raw.lower() == "none":
            return action, None

        if locator_raw.lower().startswith("text("):
            value = self._extract_quoted(locator_raw)
            if value is None:
                return None

            return action, ExtractedLocator(
                strategy=LocatorStrategy.text,
                value=value,
            )

        logger.warning(
            "DIALOG EXTRACT | unsupported hint variant: %s",
            locator_raw,
        )
        return None

    def _extract_quoted(self, text: str) -> Optional[str]:
        match = re.search(r'"([^"]*)"', text)
        return match.group(1) if match else None
