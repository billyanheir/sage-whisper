"""Transcript API endpoints."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user
from app.models.transcript import Transcript, TranscriptSegment
from app.models.voice_note import VoiceNote
from app.rate_limit import limiter
from app.schemas.transcript import TranscriptDetailResponse, TranscriptListResponse, TranscriptResponse
from app.services.transcript import get_transcript_service
from app.services.transcript_import import get_transcript_import_service
from app.services.voice_note import get_voice_note_service

logger = logging.getLogger("sage_whisper")

router = APIRouter(prefix="/api/v1/transcripts", tags=["Transcripts"])


@router.get("/", response_model=TranscriptListResponse)
def list_transcripts(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranscriptListResponse:
    """List transcripts with optional search."""
    service = get_transcript_service()
    items, total = service.get_user_transcripts(db, user.user_id, search=search, limit=limit, offset=offset)
    return TranscriptListResponse(
        items=[TranscriptResponse(**item) for item in items],
        total=total,
    )


@router.post("/import", response_model=TranscriptDetailResponse)
@limiter.limit("20/minute")
async def import_transcript(
    request: Request,
    file: UploadFile,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranscriptDetailResponse:
    """Import an existing transcript file (.txt, .vtt, .srt) bypassing Whisper."""
    import_service = get_transcript_import_service()
    vn_service = get_voice_note_service()

    # Validate file metadata
    error = import_service.validate_import_metadata(file.filename or "", file.content_type)
    if error:
        raise HTTPException(status_code=400, detail=error)

    # Store file on disk (reuse existing infrastructure)
    try:
        stored_filename, actual_size = await vn_service.store_file(user.user_id, file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    # Read stored file content for parsing
    settings = get_settings()
    stored_path = Path(settings.UPLOAD_DIR) / str(user.user_id) / stored_filename
    content = stored_path.read_text(encoding="utf-8")

    # Parse transcript content
    try:
        parsed = import_service.parse_file(content, file.filename or "import.txt")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    # Create VoiceNote record with "imported" status
    voice_note = VoiceNote(
        user_id=user.user_id,
        original_filename=file.filename or "unknown",
        stored_filename=stored_filename,
        file_size_bytes=actual_size,
        mime_type=file.content_type,
        status="imported",
    )
    db.add(voice_note)
    db.flush()

    # Create Transcript record
    transcript = Transcript(
        voice_note_id=voice_note.id,
        user_id=user.user_id,
        full_text=parsed.full_text,
        language=parsed.language,
        model_size="imported",
        processing_time_seconds=0.0,
    )
    db.add(transcript)
    db.flush()

    # Create TranscriptSegment records
    segments = []
    for seg in parsed.segments:
        segment = TranscriptSegment(
            transcript_id=transcript.id,
            segment_index=seg.index,
            start_time=seg.start_time,
            end_time=seg.end_time,
            text=seg.text,
        )
        db.add(segment)
        segments.append(segment)

    db.commit()
    db.refresh(transcript)
    for s in segments:
        db.refresh(s)

    return TranscriptDetailResponse(
        id=transcript.id,
        voice_note_id=transcript.voice_note_id,
        original_filename=voice_note.original_filename,
        full_text=transcript.full_text,
        language=transcript.language,
        model_size=transcript.model_size,
        processing_time_seconds=transcript.processing_time_seconds,
        created_at=transcript.created_at,
        segments=[
            {
                "id": s.id,
                "segment_index": s.segment_index,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "text": s.text,
            }
            for s in segments
        ],
    )


@router.get("/{transcript_id}", response_model=TranscriptDetailResponse)
def get_transcript(
    transcript_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranscriptDetailResponse:
    """Get a transcript with segments."""
    service = get_transcript_service()
    data = service.get_transcript_with_segments(db, transcript_id, user.user_id)
    if not data:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return TranscriptDetailResponse(**data)


@router.get("/{transcript_id}/download")
def download_transcript(
    transcript_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Download transcript as plain text."""
    service = get_transcript_service()
    data = service.get_transcript_with_segments(db, transcript_id, user.user_id)
    if not data:
        raise HTTPException(status_code=404, detail="Transcript not found")

    text = service.generate_download_text(data)
    filename = data["original_filename"].rsplit(".", 1)[0] + ".txt"

    return PlainTextResponse(
        content=text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
