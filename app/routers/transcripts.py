"""Transcript API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CurrentUser, get_current_user
from app.schemas.transcript import TranscriptDetailResponse, TranscriptListResponse, TranscriptResponse
from app.services.transcript import get_transcript_service

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
