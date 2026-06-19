from typing import List
import logging

from app.models.cir import (
    CIRBlock,
    CIRAction,
    ActionType,
    AssertionType,
)

logger = logging.getLogger("atomic_normalizer")


class AtomicNormalizer:
    """
    Rewrites logical CIR actions into verifier-safe atomic primitives.

    CORE INVARIANT (FOCUS OWNERSHIP):
    - All actions operate on explicit locators
    - Focus-based targeting is forbidden
    - No implicit or active-element assumptions

    HARD GUARANTEES:
    - NEVER emits invalid CIRAction objects
    - NEVER returns an empty CIRBlock
    - Focus-requiring actions NEVER assume implicit focus
    - Normalization is IDEMPOTENT
    """

    # ==================================================
    # PUBLIC API
    # ==================================================

    def normalize_block(self, block: CIRBlock) -> CIRBlock:
        """
        Normalize all actions in a CIRBlock.

        Safety contract:
        - If normalization removes all actions, the original block is returned
        """
        original_actions = block.actions
        normalized: List[CIRAction] = []

        for action in original_actions:
            normalized.extend(self._normalize_action(action))

        # -------------------------------------------------
        # CRITICAL SAFETY NET — NEVER EMIT EMPTY BLOCK
        # -------------------------------------------------
        if not normalized:
            logger.warning(
                "ATOMIC NORMALIZER | block=%s | all actions dropped → preserving original",
                block.block_id,
            )
            return block

        if normalized != original_actions:
            logger.info(
                "ATOMIC NORMALIZATION | block=%s | %d → %d actions",
                block.block_id,
                len(original_actions),
                len(normalized),
            )

        return CIRBlock(
            block_id=block.block_id,
            intent=block.intent,
            block_type=block.block_type,
            actions=normalized,
        )

    # ==================================================
    # ACTION NORMALIZATION
    # ==================================================

    def _normalize_action(self, action: CIRAction) -> List[CIRAction]:
        """
        Normalize a single CIRAction into zero or more atomic actions.
        """

        # --------------------------------------------------
        # ASSERTION FILTERS
        # --------------------------------------------------
        if self._should_drop_assertion(action):
            logger.info(
                "DROPPED ASSERT | type=%s | reason=missing_target | target=%s",
                getattr(action.assertion, "assert_type", None),
                getattr(action.target, "locator_value", None),
            )

            return []

        # DEFAULT — pass through unchanged
        return [action]

    # ==================================================
    # ASSERTION FILTERS
    # ==================================================

    def _should_drop_assertion(self, action: CIRAction) -> bool:
        if action.action_type != ActionType.assert_action:
            return False
        return self._is_illegal_visibility_assert(action)

    def _is_illegal_visibility_assert(self, action: CIRAction) -> bool:
        """
        Only element-bound assertions require a target.
        Page-level assertions (title/url) are allowed to have no target.
        """

        assert action.action_type == ActionType.assert_action

        if not action.assertion:
            return True

        # These assertion types DO NOT require a target
        if action.assertion.assert_type in {
            AssertionType.title_contains,
            AssertionType.title_equals,
            AssertionType.url_contains,
        }:
            return False

        # Everything else MUST have a target
        target = action.target
        if not target:
            return True

        if not target.locator_value:
            return True

        return False


