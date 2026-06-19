from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict


@dataclass(frozen=True)
class EmbeddingBackendSpec:
    preset: str
    model_name: str
    dimensions: int

    def to_dict(self) -> Dict[str, int | str]:
        return asdict(self)
