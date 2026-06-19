from __future__ import annotations
import difflib

class PatchDiffValidator:
    @staticmethod
    def validate(old_code: str, new_code: str) -> bool:
        if not new_code.strip():
            return False

        if old_code.strip() == new_code.strip():
            return False

        diff = list(difflib.unified_diff(
            old_code.splitlines(),
            new_code.splitlines(),
            lineterm=""
        ))

        if len(diff) < 3:
            return False

        # Guard against destructive changes
        removed_lines = [l for l in diff if l.startswith("-") and not l.startswith("---")]
        added_lines = [l for l in diff if l.startswith("+") and not l.startswith("+++")]
        
        if len(removed_lines) > 5 * len(added_lines) + 10:
            return False

        return True

    @staticmethod
    def diff(old_code: str, new_code: str) -> str:
        return "\n".join(
            difflib.unified_diff(
                old_code.splitlines(),
                new_code.splitlines(),
                lineterm=""
            )
        )
