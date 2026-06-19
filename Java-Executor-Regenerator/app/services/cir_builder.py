# app/services/cir_builder.py

from typing import Optional
import logging

from app.models.cir import (
    CIRBlock,
    CIRAction,
    ActionType,
    AssertionType,
    CIRAssertion,
    CIRBlockType,
    CIRDialog,
)
from app.models.context import StepRepairContext
from app.models.extraction import ExtractedLocator
from app.models.step_repair import StepRepairRequest
from app.core.exceptions import StepNotRepairableError

from app.services.llm_classifier import LLMActionClassifier
from app.services.extractors import (
    ClickActionExtractor,
    TypeActionExtractor,
    SelectActionExtractor,
    AssertActionExtractor,
    DialogActionExtractor,
)
from app.services.atomic_normalizer import AtomicNormalizer

logger = logging.getLogger("cir.builder")


class CIRBuilder:
    """
    STEP REPAIR CIR BUILDER.

    Responsibility:
    - Best-effort CIR construction
    - NEVER decides final repairability
    - Allows incomplete actions only when verifier/modifier can handle them
    """

    def __init__(self):
        self.classifier = LLMActionClassifier()
        self.click_extractor = ClickActionExtractor()
        self.type_extractor = TypeActionExtractor()
        self.select_extractor = SelectActionExtractor()
        self.assert_extractor = AssertActionExtractor()
        self.dialog_extractor = DialogActionExtractor()
        self.atomic_normalizer = AtomicNormalizer()

    async def build(
        self,
        *,
        request: StepRepairRequest,
        framework: str = "playwright",
    ) -> tuple[CIRBlock, StepRepairContext]:

        step_id = request.step_id
        step_intent = request.step_intent
        original_code = request.original_code

        error_message = (
            request.error_details.message
            if request.error_details
            else ""
        )

        artifacts = request.artifacts

        dom_snapshot = artifacts.dom_snapshot if artifacts else None
        error_image_bytes = artifacts.error_image_bytes if artifacts else None
        page_url = getattr(artifacts, "page_url", None)

        logger.info(
            "CIR BUILD START | step_id=%s | framework=%s | intent=%r",
            step_id,
            framework,
            step_intent,
        )

        context = StepRepairContext(
            reference_code=original_code,
        )

        # --------------------------------------------------
        # 1️⃣ Classify action
        # --------------------------------------------------
        action_type = await self.classifier.classify(
            step_intent=step_intent,
            original_code=original_code,
            error_type=request.error_classification.type
            if request.error_classification
            else None,
            error_image_bytes=error_image_bytes,
        )

        logger.info(
            "CIR CLASSIFIER RESULT | step_id=%s | action_type=%s",
            step_id,
            action_type,
        )

        actions: list[CIRAction] = []
        extractor_type: Optional[str] = None

        # --------------------------------------------------
        # 2️⃣ RUNTIME DIALOG (FALLBACK BLOCK)
        # --------------------------------------------------
        if action_type == ActionType.handle_dialog:
            extractor_type = "DIALOG"

            extracted = await self.dialog_extractor.extract(
                step_intent=step_intent,
                original_code=original_code,
                error_message=error_message,
                dom_snapshot=dom_snapshot,
                error_image_bytes=error_image_bytes,
                framework=framework,
            )

            if not extracted:
                raise StepNotRepairableError(
                    "Dialog inferred but no dialog evidence extracted",
                    details={"step_id": step_id},
                )

            dialog_action, locator = extracted

            return (
                CIRBlock(
                    block_id=f"{step_id}_fallback",
                    intent="Handle runtime dialog",
                    block_type=CIRBlockType.fallback,
                    actions=[
                        CIRAction(
                            action_type=ActionType.handle_dialog,
                            dialog=CIRDialog(
                                action=dialog_action,
                                target=self._to_cir_locator(locator),
                            ),
                        )
                    ],
                    meta={"extractor": extractor_type},
                ),
                context,
            )

        # --------------------------------------------------
        # 3️⃣ CLICK
        # --------------------------------------------------
        if action_type == ActionType.click:
            extractor_type = "CLICK"

            locator = await self.click_extractor.extract(
                step_intent=step_intent,
                original_code=original_code,
                error_message=error_message,
                dom_snapshot=dom_snapshot,
                page_url=page_url,
                error_image_bytes=error_image_bytes,
                framework=framework,
            )

            if not locator:
                raise StepNotRepairableError(
                    "Click inferred but no locator extracted",
                    details={"step_id": step_id},
                )

            actions.append(
                CIRAction(
                    action_type=ActionType.click,
                    target=self._to_cir_locator(locator),
                )
            )

        # --------------------------------------------------
        # 4️⃣ TYPE
        # --------------------------------------------------
        elif action_type == ActionType.type:
            extractor_type = "TYPE"

            locator, value = await self.type_extractor.extract(
                step_intent=step_intent,
                original_code=original_code,
                error_message=error_message,
                dom_snapshot=dom_snapshot,
                page_url=page_url,
                error_image_bytes=error_image_bytes,
                framework=framework,
            )

            if not locator:
                raise StepNotRepairableError(
                    "Type inferred but no locator extracted",
                    details={"step_id": step_id},
                )

            actions.append(
                CIRAction(
                    action_type=ActionType.type,
                    target=self._to_cir_locator(locator),
                    value=value.value if value else None,
                )
            )

        # --------------------------------------------------
        # 5️⃣ SELECT
        # --------------------------------------------------
        elif action_type == ActionType.select:
            extractor_type = "SELECT"

            locator, value = await self.select_extractor.extract(
                step_intent=step_intent,
                original_code=original_code,
                error_message=error_message,
                dom_snapshot=dom_snapshot,
                page_url=page_url,
                error_image_bytes=error_image_bytes,
                framework=framework,
            )

            if not locator:
                raise StepNotRepairableError(
                    "Select inferred but no locator extracted",
                    details={"step_id": step_id},
                )

            actions.append(
                CIRAction(
                    action_type=ActionType.select,
                    target=self._to_cir_locator(locator),
                    value=value.value if value else None,
                )
            )

        # --------------------------------------------------
        # 6️⃣ ASSERT
        # --------------------------------------------------
        elif action_type == ActionType.assert_action:
            extractor_type = "ASSERT"

            assertion = await self.assert_extractor.extract(
                step_intent=step_intent,
                original_code=original_code,
                error_message=error_message,
                dom_snapshot=dom_snapshot,
                page_url=page_url,
                error_image_bytes=error_image_bytes,
                framework=framework,
            )

            if not assertion:
                raise StepNotRepairableError(
                    "Assertion inferred but no assertion extracted",
                    details={"step_id": step_id},
                )

            cir_locator = self._to_cir_locator(assertion.locator)

            if assertion.type != AssertionType.url_contains and cir_locator is None:
                raise StepNotRepairableError(
                    "Assertion requires locator but none could be constructed",
                    details={"step_id": step_id},
                )

            actions.append(
                CIRAction(
                    action_type=ActionType.assert_action,
                    target=cir_locator,
                    assertion=CIRAssertion(
                        assert_type=assertion.type,
                        expected_value=assertion.expected,
                    ),
                )
            )

        # --------------------------------------------------
        # 7️⃣ HOVER / DOUBLE-CLICK / RIGHT-CLICK
        # --------------------------------------------------
        elif action_type in {
            ActionType.hover,
            ActionType.double_click,
            ActionType.right_click,
        }:
            extractor_type = action_type.value.upper()

            locator = await self.click_extractor.extract(
                step_intent=step_intent,
                original_code=original_code,
                error_message=error_message,
                dom_snapshot=dom_snapshot,
                page_url=page_url,
                error_image_bytes=error_image_bytes,
                framework=framework,
            )

            if not locator:
                raise StepNotRepairableError(
                    f"{action_type.value} inferred but no locator extracted",
                    details={"step_id": step_id},
                )

            actions.append(
                CIRAction(
                    action_type=action_type,
                    target=self._to_cir_locator(locator),
                )
            )

        # --------------------------------------------------
        # 8️⃣ DRAG & DROP
        # --------------------------------------------------
        elif action_type == ActionType.drag_drop:
            extractor_type = "DRAG_DROP"

            locator = await self.click_extractor.extract(
                step_intent=step_intent,
                original_code=original_code,
                error_message=error_message,
                dom_snapshot=dom_snapshot,
                page_url=page_url,
                error_image_bytes=error_image_bytes,
                framework=framework,
            )

            if not locator:
                raise StepNotRepairableError(
                    "drag_drop inferred but no source locator extracted",
                    details={"step_id": step_id},
                )

            actions.append(
                CIRAction(
                    action_type=ActionType.drag_drop,
                    target=self._to_cir_locator(locator),
                    # drag_target left None; generator uses scroll area or modifier fills it
                )
            )

        # --------------------------------------------------
        # 9️⃣ KEYBOARD
        # --------------------------------------------------
        elif action_type == ActionType.keyboard:
            extractor_type = "KEYBOARD"

            # Best-effort: extract key combo from intent or code
            import re as _re
            combo_match = _re.search(
                r"(?:ctrl|cmd|alt|shift|meta)\s*\+\s*[\w]+",
                step_intent,
                _re.IGNORECASE,
            )
            if not combo_match:
                combo_match = _re.search(
                    r"(?:ctrl|cmd|alt|shift|meta)\s*\+\s*[\w]+",
                    original_code,
                    _re.IGNORECASE,
                )

            key_combination = combo_match.group(0) if combo_match else "Ctrl+A"

            actions.append(
                CIRAction(
                    action_type=ActionType.keyboard,
                    key_combination=key_combination,
                )
            )

        # --------------------------------------------------
        # 🔟 SCROLL
        # --------------------------------------------------
        elif action_type == ActionType.scroll:
            extractor_type = "SCROLL"

            import re as _re
            direction_match = _re.search(
                r"\b(up|down|left|right)\b",
                step_intent,
                _re.IGNORECASE,
            )
            scroll_direction = direction_match.group(1).lower() if direction_match else "down"

            actions.append(
                CIRAction(
                    action_type=ActionType.scroll,
                    scroll_direction=scroll_direction,
                    scroll_amount=300,
                )
            )

        # --------------------------------------------------
        # 1️⃣1️⃣ UPLOAD FILE
        # --------------------------------------------------
        elif action_type == ActionType.upload_file:
            extractor_type = "UPLOAD_FILE"

            locator = await self.click_extractor.extract(
                step_intent=step_intent,
                original_code=original_code,
                error_message=error_message,
                dom_snapshot=dom_snapshot,
                page_url=page_url,
                error_image_bytes=error_image_bytes,
                framework=framework,
            )

            import re as _re
            path_match = _re.search(
                r'["\']([^"\']*\.[a-zA-Z0-9]{2,5})["\']',
                step_intent + " " + original_code,
            )
            file_path = path_match.group(1) if path_match else "/tmp/upload.txt"

            actions.append(
                CIRAction(
                    action_type=ActionType.upload_file,
                    target=self._to_cir_locator(locator) if locator else None,
                    file_path_to_upload=file_path,
                )
            )

        # --------------------------------------------------
        # 1️⃣2️⃣ SWITCH FRAME
        # --------------------------------------------------
        elif action_type == ActionType.switch_frame:
            extractor_type = "SWITCH_FRAME"

            import re as _re
            frame_match = _re.search(
                r'(?:frame[_\s]?locator|iframe|switch.*frame)\s*[=(]\s*["\']([^"\']+)["\']',
                original_code,
                _re.IGNORECASE,
            )
            frame_locator = frame_match.group(1) if frame_match else None

            actions.append(
                CIRAction(
                    action_type=ActionType.switch_frame,
                    frame_locator=frame_locator,
                )
            )

        # --------------------------------------------------
        # 1️⃣3️⃣ SWITCH WINDOW
        # --------------------------------------------------
        elif action_type == ActionType.switch_window:
            extractor_type = "SWITCH_WINDOW"

            import re as _re
            idx_match = _re.search(r"\b(\d+)\b", step_intent)
            window_index = int(idx_match.group(1)) if idx_match else 1

            actions.append(
                CIRAction(
                    action_type=ActionType.switch_window,
                    window_index=window_index,
                )
            )

        # --------------------------------------------------
        # 1️⃣4️⃣ EXECUTE SCRIPT
        # --------------------------------------------------
        elif action_type == ActionType.execute_script:
            extractor_type = "EXECUTE_SCRIPT"

            import re as _re
            script_match = _re.search(
                r'execute_script\s*\(\s*["\']([^"\']+)["\']',
                original_code,
                _re.IGNORECASE,
            )
            if not script_match:
                script_match = _re.search(
                    r'evaluate\s*\(\s*["\']([^"\']+)["\']',
                    original_code,
                    _re.IGNORECASE,
                )
            script_expression = script_match.group(1) if script_match else "window.scrollBy(0, 300)"

            actions.append(
                CIRAction(
                    action_type=ActionType.execute_script,
                    script_expression=script_expression,
                )
            )

        # --------------------------------------------------
        # 1️⃣5️⃣ WAIT FOR
        # --------------------------------------------------
        elif action_type == ActionType.wait_for:
            extractor_type = "WAIT_FOR"

            from app.models.cir import WaitCondition as _WC
            import re as _re
            condition = _WC.visible
            if _re.search(r"\bhidden\b|\bnot visible\b", step_intent, _re.IGNORECASE):
                condition = _WC.hidden
            elif _re.search(r"\bload\b|\bnetwork\b", step_intent, _re.IGNORECASE):
                condition = _WC.load_state

            timeout_match = _re.search(r"\b(\d+)\s*(?:ms|s|second)", step_intent, _re.IGNORECASE)
            timeout_ms = int(timeout_match.group(1)) * 1000 if timeout_match else 5000

            actions.append(
                CIRAction(
                    action_type=ActionType.wait_for,
                    wait_for_condition=condition,
                    wait_for_timeout=timeout_ms,
                )
            )

        # --------------------------------------------------
        # FINAL SAFETY GATE
        # --------------------------------------------------
        if not actions:
            raise StepNotRepairableError(
                "Action classified but no CIR actions produced",
                details={
                    "step_id": step_id,
                    "action_type": str(action_type),
                },
            )

        logger.info(
            "CIR BUILD COMPLETE | step_id=%s | actions=%d | extractor=%s",
            step_id,
            len(actions),
            extractor_type,
        )

        block = CIRBlock(
            block_id=step_id,
            intent=step_intent,
            block_type=CIRBlockType.step,
            actions=actions,
            meta={"extractor": extractor_type},
        )


        block = self.atomic_normalizer.normalize_block(block)

        return block, context

    def _to_cir_locator(self, extracted: Optional[ExtractedLocator]):
        return extracted.to_cir() if extracted else None
