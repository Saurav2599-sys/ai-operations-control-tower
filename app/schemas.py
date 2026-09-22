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
    assigned_employee_id: Optional[int]
    assigned_at: Optional[datetime]
    ai_suggested_skills: Optional[str]
    ai_suggested_priority: Optional[str]
    ai_confidence: Optional[float]
    ai_reasoning: Optional[str]
    ai_classified_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class EmployeeCreate(BaseModel):
    name: str = Field(..., description="Employee name")
    location: Optional[str] = None
    skills: Optional[str] = Field(
        default=None, description="Comma-separated skills, e.g. 'plumbing,hvac'"
    )
    daily_capacity: int = Field(
        default=5, ge=1, description="Max orders this employee can be assigned per run"
    )


class EmployeeOut(BaseModel):
    id: int
    name: str
    location: Optional[str]
    skills: Optional[str]
    daily_capacity: int
    created_at: datetime

    class Config:
        from_attributes = True


class AssignmentRunResult(BaseModel):
    strategy: str
    considered: int
    assigned: int
    unassigned: int
    assigned_order_ids: list[int]
