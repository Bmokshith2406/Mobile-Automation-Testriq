# app/models/batch.py
"""
Batch Processing Models

Models for batch test case generation.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

from app.models.test_case import TestCase


class BatchStatus(str, Enum):
    """Status of a batch job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"  # Some succeeded, some failed
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchItemStatus(str, Enum):
    """Status of individual item in batch."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class BatchItem(BaseModel):
    """Individual item in a batch."""
    test_case: TestCase
    priority: int = Field(default=0, description="Higher priority = processed first")
    
    model_config = {"extra": "forbid"}


class BatchRequest(BaseModel):
    """Request for batch processing."""
    items: List[BatchItem] = Field(
        ...,
        min_length=1,
        description="List of test cases to process",
    )
    parallel: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of parallel workers",
    )
    stop_on_error: bool = Field(
        default=False,
        description="Stop processing on first error",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="URL for completion notification",
    )
    
    model_config = {"extra": "forbid"}


class BatchItemResult(BaseModel):
    """Result for a single batch item."""
    test_case_id: str
    status: BatchItemStatus
    script_path: Optional[str] = None
    error: Optional[str] = None
    duration_ms: float = 0
    tokens_used: int = 0
    
    model_config = {"extra": "ignore"}


class BatchResult(BaseModel):
    """Result of batch processing."""
    batch_id: str
    status: BatchStatus
    total_items: int
    completed_items: int
    failed_items: int
    skipped_items: int = 0
    results: List[BatchItemResult]
    total_duration_ms: float
    total_tokens_used: int
    cost_estimate_usd: float
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"extra": "ignore"}


class BatchProgress(BaseModel):
    """Progress update for batch processing."""
    batch_id: str
    status: BatchStatus
    total_items: int
    completed_items: int
    current_item: Optional[str] = None
    progress_percent: float
    estimated_remaining_seconds: Optional[float] = None
    
    model_config = {"extra": "ignore"}

