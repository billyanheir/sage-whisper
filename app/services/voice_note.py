"""Voice note service for upload validation, storage, and CRUD."""

import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.voice_note import VoiceNote

ALLOWED_EXTENSIONS = {".mp3", ".m4a", ".wav", ".webm", ".ogg", ".flac"}
ALLOWED_MIME_TYPES = {
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/ogg",
    "audio/flac",
    "audio/x-flac",
}


class VoiceNoteService:
    """Handles voice note upload, storage, and management."""

    def validate_upload(self, filename: str, content_type: str | None, file_size: int) -> str | None:
        """Validate upload file. Returns error message or None if valid."""
        settings = get_settings()

        # Check extension
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

        # Check MIME type (relaxed — some browsers send generic types)
        if content_type and content_type not in ALLOWED_MIME_TYPES and not content_type.startswith("audio/"):
            return f"Invalid content type '{content_type}'. Must be an audio file."

        # Check size
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if file_size > max_bytes:
            return f"File too large ({file_size // (1024 * 1024)}MB). Maximum: {settings.MAX_UPLOAD_SIZE_MB}MB"

        return None

    async def store_file(self, user_id: int, upload: UploadFile) -> tuple[str, int]:
        """Stream uploaded file to disk. Returns (stored_filename, file_size_bytes)."""
        settings = get_settings()
        ext = Path(upload.filename or "audio.bin").suffix.lower()
        stored_filename = f"{uuid.uuid4()}{ext}"
        user_dir = Path(settings.UPLOAD_DIR) / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        file_path = user_dir / stored_filename
        file_size = 0
        chunk_size = 1024 * 64  # 64KB chunks

        with open(file_path, "wb") as f:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                file_size += len(chunk)

        return stored_filename, file_size

    def create_voice_note(
        self,
        db: Session,
        user_id: int,
        original_filename: str,
        stored_filename: str,
        file_size_bytes: int,
        mime_type: str | None,
    ) -> VoiceNote:
        """Create a voice note record in the database."""
        note = VoiceNote(
            user_id=user_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            status="uploaded",
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        return note

    def get_user_voice_notes(self, db: Session, user_id: int) -> list[VoiceNote]:
        """Get all voice notes for a user, newest first."""
        return db.query(VoiceNote).filter(VoiceNote.user_id == user_id).order_by(VoiceNote.created_at.desc()).all()

    def get_voice_note(self, db: Session, note_id: int, user_id: int) -> VoiceNote | None:
        """Get a single voice note by ID, scoped to user."""
        return db.query(VoiceNote).filter(VoiceNote.id == note_id, VoiceNote.user_id == user_id).first()

    def delete_voice_note(self, db: Session, note: VoiceNote) -> None:
        """Delete a voice note record and its file."""
        settings = get_settings()
        file_path = Path(settings.UPLOAD_DIR) / str(note.user_id) / note.stored_filename
        if file_path.exists():
            os.remove(file_path)
        db.delete(note)
        db.commit()


_voice_note_service: VoiceNoteService | None = None


def get_voice_note_service() -> VoiceNoteService:
    """Get singleton voice note service instance."""
    global _voice_note_service
    if _voice_note_service is None:
        _voice_note_service = VoiceNoteService()
    return _voice_note_service
