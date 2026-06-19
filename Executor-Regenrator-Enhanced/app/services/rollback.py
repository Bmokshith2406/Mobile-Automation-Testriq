from __future__ import annotations
from pathlib import Path

class RollbackManager:
    def __init__(self):
        self._backups: dict[str, Path] = {}

    def register(self, key: str, backup_path: Path):
        self._backups[key] = backup_path

    def rollback(self, key: str, target_path: Path) -> bool:
        backup = self._backups.get(key)
        if not backup or not backup.exists():
            return False

        backup.replace(target_path)
        return True
