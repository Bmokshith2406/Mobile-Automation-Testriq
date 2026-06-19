# app/services/atomic_normalizer.py

from typing import List
import logging

from app.models.cir import (
    CIRBlock,
    CIRAction,
    ActionType,
    CIRLocator,
    LocatorStrategy,
)

logger = logging.getLogger("atomic_normalizer")


class AtomicNormalizer:
    """
    Rewrites logical CIR actions into verifier-safe atomic primitives.

    CORE INVARIANT (FOCUS OWNERSHIP):
    - Any action that REQUIRES focus must operate on the active element
    - Any action with an explicit target that requires focus must
      explicitly establish focus first

    HARD GUARANTEES:
    - NEVER emits invalid CIRAction objects
    - NEVER removes intent
    - NEVER applies semantic heuristics
    - Normalization is IDEMPOTENT
    """

    # --------------------------------------------------
    # Explicit focus-requiring actions (future-safe)
    # --------------------------------------------------
    FOCUS_REQUIRED_ACTIONS = {
        ActionType.type,
        ActionType.keyboard,
    }

    # ==================================================
    # PUBLIC API
    # ==================================================

    def normalize_block(self, block: CIRBlock) -> CIRBlock:
        """
        Normalize all actions in a CIRBlock.

        Safety contract:
        - Never emit an empty block
        - If normalization produces no actions, original block is returned
        """

        logger.debug(
            "ATOMIC NORMALIZER ENTER | block_id=%s | block_type=%s | actions=%d",
            block.block_id,
            block.block_type,
            len(block.actions),
        )

        original_actions = block.actions
        normalized: List[CIRAction] = []

        for action in original_actions:
            normalized.extend(self._normalize_action(action))

        # -------------------------------------------------
        # CRITICAL SAFETY NET — NEVER EMIT EMPTY BLOCK
        # -------------------------------------------------
        if not normalized:
            logger.warning(
                "ATOMIC NORMALIZER EMPTY | block=%s | preserving original actions",
                block.block_id,
            )
            return block

        # -------------------------------------------------
        # STRUCTURAL CHANGE LOG (SIGNAL ONLY)
        # -------------------------------------------------
        if normalized != original_actions:
            logger.info(
                "ATOMIC NORMALIZATION APPLIED | block=%s | %d → %d actions",
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

        # Guard: valueless type actions should not be rewritten
        if action.action_type == ActionType.type and action.value is None:
            return [action]

        # Focus-requiring action with explicit target (non-idempotent case only)
        if (
            self._requires_focus(action)
            and action.target is not None
            and not self._is_active_element(action.target)
        ):
            logger.debug(
                "ATOMIC NORMALIZER REWRITE | action_type=%s | target=%s:%s",
                action.action_type,
                action.target.locator_strategy,
                action.target.locator_value,
            )
            return self._rewrite_focus_required_action(action)

        # DEFAULT — pass through unchanged
        return [action]

    # ==================================================
    # FOCUS OWNERSHIP LOGIC
    # ==================================================

    def _requires_focus(self, action: CIRAction) -> bool:
        """
        Actions that cannot function correctly unless an element is focused.
        """
        return action.action_type in self.FOCUS_REQUIRED_ACTIONS

    def _rewrite_focus_required_action(self, action: CIRAction) -> List[CIRAction]:
        """
        Rewrite a focus-requiring action with explicit target into:

            1. CLICK(target)        -> establishes focus
            2. ACTION(:focus)       -> operates on active element

        Properties:
        - Idempotent
        - Wait semantics preserved
        - Free of heuristics
        """

        # Click establishes focus (NO wait transfer)
        click = CIRAction(
            action_type=ActionType.click,
            target=action.target,
            wait=None,
        )

        # Semantic action operates on active element (wait preserved)
        focused_action = CIRAction(
            action_type=action.action_type,
            target=self._active_element_locator(),
            value=action.value,
            wait=action.wait,
        )

        return [click, focused_action]

    # ==================================================
    # ACTIVE ELEMENT LOGIC
    # ==================================================

    def _is_active_element(self, locator: CIRLocator) -> bool:
        return (
            locator.locator_strategy == LocatorStrategy.css
            and locator.locator_value == ":focus"
        )

    def _active_element_locator(self) -> CIRLocator:
        """
        Canonical locator for the active element.
        """
        return CIRLocator(
            locator_strategy=LocatorStrategy.css,
            locator_value=":focus",
        )
