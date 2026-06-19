# app/models/webhook.py
"""
Webhook Configuration Models
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional


class WebhookConfig(BaseModel):
    """Configuration for webhook notifications."""
    
    url: HttpUrl = Field(..., description="Webhook endpoint URL")
    secret: Optional[str] = Field(
        None,
        description="Optional secret for HMAC signature",
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://example.com/webhook",
                "secret": "optional-secret-key",
            }
        }

