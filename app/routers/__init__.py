"""API routers."""

from app.routers.auth import router as auth_router
from app.routers.transcripts import router as transcripts_router
from app.routers.voice_notes import router as voice_notes_router

__all__ = ["auth_router", "voice_notes_router", "transcripts_router"]
