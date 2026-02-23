"""Voice note API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CurrentUser, get_current_user
from app.rate_limit import limiter
from app.schemas.voice_note import VoiceNoteListResponse, VoiceNoteResponse
from app.services.transcription import get_transcription_service
from app.services.voice_note import get_voice_note_service

router = APIRouter(prefix="/api/v1/voice-notes", tags=["Voice Notes"])


@router.post("/", response_model=VoiceNoteResponse)
@limiter.limit("20/minute")
async def upload_voice_note(
    request: Request,
    file: UploadFile,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VoiceNoteResponse:
    """Upload an audio file as a voice note."""
    service = get_voice_note_service()

    # Validate extension + MIME type (no file read needed)
    error = service.validate_upload_metadata(file.filename or "", file.content_type)
    if error:
        raise HTTPException(status_code=400, detail=error)

    # Stream directly to disk (single read, with size limit enforcement)
    try:
        stored_filename, actual_size = await service.store_file(user.user_id, file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    note = service.create_voice_note(
        db=db,
        user_id=user.user_id,
        original_filename=file.filename or "unknown",
        stored_filename=stored_filename,
        file_size_bytes=actual_size,
        mime_type=file.content_type,
    )

    return VoiceNoteResponse.model_validate(note)


@router.get("/", response_model=VoiceNoteListResponse)
def list_voice_notes(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VoiceNoteListResponse:
    """List all voice notes for the current user."""
    service = get_voice_note_service()
    notes = service.get_user_voice_notes(db, user.user_id)
    return VoiceNoteListResponse(
        items=[VoiceNoteResponse.model_validate(n) for n in notes],
        total=len(notes),
    )


@router.get("/{note_id}", response_model=VoiceNoteResponse)
def get_voice_note(
    note_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VoiceNoteResponse:
    """Get a single voice note by ID."""
    service = get_voice_note_service()
    note = service.get_voice_note(db, note_id, user.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Voice note not found")
    return VoiceNoteResponse.model_validate(note)


@router.delete("/{note_id}")
def delete_voice_note(
    note_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a voice note."""
    service = get_voice_note_service()
    note = service.get_voice_note(db, note_id, user.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Voice note not found")
    service.delete_voice_note(db, note)
    return {"detail": "Voice note deleted"}


@router.post("/{note_id}/transcribe")
def transcribe_voice_note(
    note_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Transcribe a voice note using faster-whisper."""
    vn_service = get_voice_note_service()
    note = vn_service.get_voice_note(db, note_id, user.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Voice note not found")

    if note.status not in ("uploaded", "failed"):
        raise HTTPException(status_code=400, detail=f"Cannot transcribe note with status '{note.status}'")

    tx_service = get_transcription_service()
    transcript = tx_service.transcribe(db, note)

    return {"detail": "Transcription complete", "transcript_id": transcript.id}
