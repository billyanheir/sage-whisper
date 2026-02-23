"""Pydantic schemas for transcript endpoints."""

from datetime import datetime

from pydantic import BaseModel


class TranscriptSegmentResponse(BaseModel):
    id: int
    segment_index: int
    start_time: float
    end_time: float
    text: str

    model_config = {"from_attributes": True}


class TranscriptResponse(BaseModel):
    id: int
    voice_note_id: int
    original_filename: str | None = None
    full_text: str
    language: str | None
    model_size: str
    processing_time_seconds: float
    created_at: datetime

    model_config = {"from_attributes": True}


class TranscriptDetailResponse(TranscriptResponse):
    segments: list[TranscriptSegmentResponse] = []


class TranscriptListResponse(BaseModel):
    items: list[TranscriptResponse]
    total: int
