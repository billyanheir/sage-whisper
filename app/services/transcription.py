"""Transcription service using faster-whisper."""

import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.transcript import Transcript, TranscriptSegment
from app.models.voice_note import VoiceNote


class TranscriptionService:
    """Handles audio transcription using faster-whisper."""

    def __init__(self) -> None:
        self._model = None

    def _get_model(self):
        """Lazy-load the whisper model."""
        if self._model is None:
            from faster_whisper import WhisperModel

            settings = get_settings()
            self._model = WhisperModel(settings.WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, db: Session, voice_note: VoiceNote) -> Transcript:
        """Transcribe a voice note. Updates status and creates transcript + segments."""
        settings = get_settings()

        # Update status
        voice_note.status = "transcribing"
        db.commit()

        file_path = Path(settings.UPLOAD_DIR) / str(voice_note.user_id) / voice_note.stored_filename

        try:
            start_time = time.time()
            model = self._get_model()
            segments_iter, info = model.transcribe(str(file_path), beam_size=5)

            segments_list = list(segments_iter)
            processing_time = time.time() - start_time

            full_text = " ".join(seg.text.strip() for seg in segments_list)

            # Create transcript
            transcript = Transcript(
                voice_note_id=voice_note.id,
                user_id=voice_note.user_id,
                full_text=full_text,
                language=info.language if info else None,
                model_size=settings.WHISPER_MODEL_SIZE,
                processing_time_seconds=round(processing_time, 2),
            )
            db.add(transcript)
            db.flush()

            # Create segments
            for idx, seg in enumerate(segments_list):
                segment = TranscriptSegment(
                    transcript_id=transcript.id,
                    segment_index=idx,
                    start_time=seg.start,
                    end_time=seg.end,
                    text=seg.text.strip(),
                )
                db.add(segment)

            # Update voice note
            voice_note.status = "completed"
            if hasattr(info, "duration") and info.duration:
                voice_note.duration_seconds = info.duration

            db.commit()
            db.refresh(transcript)
            return transcript

        except Exception as e:
            voice_note.status = "failed"
            db.commit()
            raise RuntimeError(f"Transcription failed: {e}") from e


_transcription_service: TranscriptionService | None = None


def get_transcription_service() -> TranscriptionService:
    """Get singleton transcription service instance."""
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = TranscriptionService()
    return _transcription_service
