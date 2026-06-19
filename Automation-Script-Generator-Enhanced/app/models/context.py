#app/models/context.py

from typing import Optional
from pydantic import BaseModel, Field


class CIRBlockContext(BaseModel):
    """
    Metadata for a CIR block.
    Not executable. Not part of CIR.
    Used only during CIR build for diagnostics.
    """

    matched_script: Optional[str] = None

    drop_reason: Optional[str] = Field(
        default=None,
        description="Reason why this CIR block was dropped during build"
    )

    semantic_group: Optional[str] = Field(
        default=None,
        description="Composite intent group (e.g. login, search)"
    )

    is_composite: bool = Field(
        default=False,
        description="Whether this block is part of a composite step"
    )

    model_config = {
        "extra": "forbid"
    }

