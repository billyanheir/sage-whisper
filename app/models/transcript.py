"""Transcript and segment models."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.database import Base


class Transcript(Base):
    """Transcription result for a voice note."""

    __tablename__ = "transcript"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voice_note_id = Column(Integer, ForeignKey("voice_note.id"), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    full_text = Column(Text, nullable=False)
    language = Column(String(32), nullable=True)
    model_size = Column(String(32), nullable=False)
    processing_time_seconds = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TranscriptSegment(Base):
    """Timestamped segment within a transcript."""

    __tablename__ = "transcript_segment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transcript_id = Column(Integer, ForeignKey("transcript.id"), nullable=False, index=True)
    segment_index = Column(Integer, nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
