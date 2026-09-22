"""Pydantic request/response models -- the actual public contract of the
API, kept separate from the SQLAlchemy models (app/models.py), which are the
storage shape. The two are allowed to diverge on purpose.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    customer_name: str = Field(..., description="Who the order is for")
    description: str = Field(..., description="What's being requested")
    location: Optional[str] = None
    priority: Optional[str] = Field(
        default="normal", description="One of: low, normal, high, urgent"
    )
    required_skills: Optional[str] = Field(
        default=None, description="Comma-separated skills needed to fulfill this order"
    )


class OrderOut(BaseModel):
    id: int
    customer_name: str
    description: str
    location: Optional[str]
    priority: str
    required_skills: Optional[str]
    status: str
    validation_errors: list[str] = []
    duplicate_of_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True
