"""Pydantic schemas for voice note endpoints."""

from datetime import datetime

from pydantic import BaseModel


class VoiceNoteResponse(BaseModel):
    id: int
    original_filename: str
    file_size_bytes: int
    mime_type: str | None
    duration_seconds: float | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class VoiceNoteListResponse(BaseModel):
    items: list[VoiceNoteResponse]
    total: int
