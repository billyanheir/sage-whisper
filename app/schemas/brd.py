"""Pydantic schemas for BRD endpoints."""

from datetime import datetime

from pydantic import BaseModel


class BRDRequirementResponse(BaseModel):
    id: int
    brd_id: int
    requirement_text: str
    category: str
    priority: str
    status: str
    sort_order: int
    parent_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BRDRequirementUpdate(BaseModel):
    status: str | None = None
    requirement_text: str | None = None
    category: str | None = None
    priority: str | None = None


class BRDResponse(BaseModel):
    id: int
    transcript_id: int
    user_id: int
    title: str
    status: str
    project_context: str | None = None
    github_repo_url: str | None = None
    parent_brd_id: int | None = None
    created_at: datetime
    finalized_at: datetime | None = None
    requirements: list[BRDRequirementResponse] = []

    model_config = {"from_attributes": True}


class BRDListResponse(BaseModel):
    items: list[BRDResponse]
    total: int
