"""BRD API endpoints."""

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.dependencies import CurrentUser, get_current_user
from app.models.brd import BRD
from app.models.transcript import Transcript
from app.schemas.brd import BRDRequirementResponse, BRDRequirementUpdate, BRDResponse
from app.services.brd import get_brd_service

logger = logging.getLogger("sage_whisper")

router = APIRouter(prefix="/api/v1/brd", tags=["BRD"])

_session_factory = None


def _run_brd_generation(brd_id: int) -> None:
    """Run BRD generation in a background thread with its own DB session."""
    factory = _session_factory or SessionLocal
    db = factory()
    try:
        brd_service = get_brd_service()
        brd_service.generate_brd(db, brd_id)
        logger.info("BRD generation complete for BRD %d", brd_id)
    except Exception:
        logger.exception("Background BRD generation failed for BRD %d", brd_id)
    finally:
        db.close()


@router.post("/generate")
def generate_brd(
    transcript_id: int,
    parent_brd_id: int | None = None,
    project_context: str | None = None,
    github_repo_url: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Create a BRD and kick off generation in background."""
    # Verify transcript belongs to user
    transcript = db.query(Transcript).filter(Transcript.id == transcript_id, Transcript.user_id == user.user_id).first()
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    # Verify parent BRD if provided
    if parent_brd_id:
        parent = db.query(BRD).filter(BRD.id == parent_brd_id, BRD.user_id == user.user_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent BRD not found")

    from app.models.voice_note import VoiceNote

    voice_note = db.query(VoiceNote).filter(VoiceNote.id == transcript.voice_note_id).first()
    title = f"BRD - {voice_note.original_filename}" if voice_note else f"BRD - Transcript #{transcript_id}"

    from datetime import datetime

    brd = BRD(
        transcript_id=transcript_id,
        user_id=user.user_id,
        title=title,
        status="generating",
        project_context=project_context,
        github_repo_url=github_repo_url,
        parent_brd_id=parent_brd_id,
        created_at=datetime.utcnow(),
    )
    db.add(brd)
    db.commit()
    db.refresh(brd)

    # Run generation in background thread
    thread = threading.Thread(target=_run_brd_generation, args=(brd.id,), daemon=True)
    thread.start()

    return {"brd_id": brd.id, "detail": "BRD generation started"}


@router.get("/{brd_id}", response_model=BRDResponse)
def get_brd(
    brd_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BRDResponse:
    """Get a BRD with all requirements."""
    brd_service = get_brd_service()
    brd_data = brd_service.get_brd(db, brd_id, user.user_id)
    if not brd_data:
        raise HTTPException(status_code=404, detail="BRD not found")
    return BRDResponse(
        id=brd_data["id"],
        transcript_id=brd_data["transcript_id"],
        user_id=brd_data["user_id"],
        title=brd_data["title"],
        status=brd_data["status"],
        project_context=brd_data["project_context"],
        github_repo_url=brd_data["github_repo_url"],
        parent_brd_id=brd_data["parent_brd_id"],
        created_at=brd_data["created_at"],
        finalized_at=brd_data["finalized_at"],
        requirements=[BRDRequirementResponse.model_validate(r) for r in brd_data["requirements"]],
    )


@router.patch("/{brd_id}/requirements/{req_id}", response_model=BRDRequirementResponse)
def update_requirement(
    brd_id: int,
    req_id: int,
    updates: BRDRequirementUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BRDRequirementResponse:
    """Update a requirement (approve, edit, reject)."""
    brd_service = get_brd_service()
    # Verify BRD belongs to user
    brd_data = brd_service.get_brd(db, brd_id, user.user_id)
    if not brd_data:
        raise HTTPException(status_code=404, detail="BRD not found")

    req = brd_service.update_requirement(db, req_id, user.user_id, updates.model_dump(exclude_none=True))
    if not req:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return BRDRequirementResponse.model_validate(req)


@router.post("/{brd_id}/requirements/{req_id}/split")
def split_requirement(
    brd_id: int,
    req_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Split a requirement into sub-requirements via Ollama."""
    brd_service = get_brd_service()
    brd_data = brd_service.get_brd(db, brd_id, user.user_id)
    if not brd_data:
        raise HTTPException(status_code=404, detail="BRD not found")

    children = brd_service.split_requirement(db, req_id, user.user_id)
    return {
        "detail": f"Requirement split into {len(children)} sub-requirements",
        "requirements": [BRDRequirementResponse.model_validate(c) for c in children],
    }


@router.post("/{brd_id}/finalize", response_model=BRDResponse)
def finalize_brd(
    brd_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BRDResponse:
    """Finalize a BRD after review."""
    brd_service = get_brd_service()
    brd = brd_service.finalize_brd(db, brd_id, user.user_id)
    if not brd:
        raise HTTPException(status_code=404, detail="BRD not found")

    brd_data = brd_service.get_brd(db, brd_id, user.user_id)
    return BRDResponse(
        id=brd_data["id"],
        transcript_id=brd_data["transcript_id"],
        user_id=brd_data["user_id"],
        title=brd_data["title"],
        status=brd_data["status"],
        project_context=brd_data["project_context"],
        github_repo_url=brd_data["github_repo_url"],
        parent_brd_id=brd_data["parent_brd_id"],
        created_at=brd_data["created_at"],
        finalized_at=brd_data["finalized_at"],
        requirements=[BRDRequirementResponse.model_validate(r) for r in brd_data["requirements"]],
    )


@router.get("/{brd_id}/download")
def download_brd(
    brd_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Download BRD as Markdown."""
    brd_service = get_brd_service()
    markdown = brd_service.generate_markdown(db, brd_id, user.user_id)
    if not markdown:
        raise HTTPException(status_code=404, detail="BRD not found")

    brd = db.query(BRD).filter(BRD.id == brd_id, BRD.user_id == user.user_id).first()
    filename = f"brd_{brd_id}.md" if not brd else f"{brd.title.replace(' ', '_')}.md"

    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
