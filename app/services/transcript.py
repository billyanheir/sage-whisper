"""Transcript service for retrieval and export."""

from sqlalchemy.orm import Session

from app.models.transcript import Transcript, TranscriptSegment
from app.models.voice_note import VoiceNote


class TranscriptService:
    """Handles transcript retrieval, search, and export."""

    def get_user_transcripts(
        self, db: Session, user_id: int, search: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Get transcripts for a user with optional text search. Returns (items, total_count)."""
        query = (
            db.query(Transcript, VoiceNote.original_filename)
            .join(VoiceNote, Transcript.voice_note_id == VoiceNote.id)
            .filter(Transcript.user_id == user_id)
        )

        if search:
            query = query.filter(Transcript.full_text.ilike(f"%{search}%"))

        total = query.count()
        results = query.order_by(Transcript.created_at.desc()).offset(offset).limit(limit).all()

        items = []
        for transcript, original_filename in results:
            items.append(
                {
                    "id": transcript.id,
                    "voice_note_id": transcript.voice_note_id,
                    "original_filename": original_filename,
                    "full_text": transcript.full_text,
                    "language": transcript.language,
                    "model_size": transcript.model_size,
                    "processing_time_seconds": transcript.processing_time_seconds,
                    "created_at": transcript.created_at,
                }
            )
        return items, total

    def get_transcript_with_segments(self, db: Session, transcript_id: int, user_id: int) -> dict | None:
        """Get a transcript with all its segments."""
        result = (
            db.query(Transcript, VoiceNote.original_filename)
            .join(VoiceNote, Transcript.voice_note_id == VoiceNote.id)
            .filter(Transcript.id == transcript_id, Transcript.user_id == user_id)
            .first()
        )

        if not result:
            return None

        transcript, original_filename = result
        segments = (
            db.query(TranscriptSegment)
            .filter(TranscriptSegment.transcript_id == transcript_id)
            .order_by(TranscriptSegment.segment_index)
            .all()
        )

        return {
            "id": transcript.id,
            "voice_note_id": transcript.voice_note_id,
            "original_filename": original_filename,
            "full_text": transcript.full_text,
            "language": transcript.language,
            "model_size": transcript.model_size,
            "processing_time_seconds": transcript.processing_time_seconds,
            "created_at": transcript.created_at,
            "segments": segments,
        }

    def get_transcript_by_voice_note(self, db: Session, voice_note_id: int, user_id: int) -> Transcript | None:
        """Get transcript for a specific voice note."""
        return (
            db.query(Transcript)
            .filter(Transcript.voice_note_id == voice_note_id, Transcript.user_id == user_id)
            .first()
        )

    def generate_download_text(self, transcript_data: dict) -> str:
        """Generate a plain text download of the transcript with timestamps."""
        lines = []
        lines.append(f"Transcript: {transcript_data['original_filename']}")
        lines.append(f"Language: {transcript_data.get('language', 'unknown')}")
        lines.append(f"Model: {transcript_data['model_size']}")
        lines.append(f"Date: {transcript_data['created_at']}")
        lines.append("")
        lines.append("=" * 60)
        lines.append("")

        for seg in transcript_data.get("segments", []):
            start_min = int(seg.start_time // 60)
            start_sec = int(seg.start_time % 60)
            lines.append(f"[{start_min:02d}:{start_sec:02d}] {seg.text}")

        lines.append("")
        lines.append("=" * 60)
        lines.append("")
        lines.append("Full Text:")
        lines.append(transcript_data["full_text"])

        return "\n".join(lines)


_transcript_service: TranscriptService | None = None


def get_transcript_service() -> TranscriptService:
    """Get singleton transcript service instance."""
    global _transcript_service
    if _transcript_service is None:
        _transcript_service = TranscriptService()
    return _transcript_service
