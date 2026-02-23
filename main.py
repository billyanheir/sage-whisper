"""Sage Whisper - Voice Note Transcription App."""

import logging
import time

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.database import get_db
from app.dependencies import (
    clear_auth_cookie,
    get_current_user_from_cookie,
    require_web_auth,
    set_auth_cookie,
)
from app.rate_limit import limiter
from app.routers import auth_router, transcripts_router, voice_notes_router
from app.services.auth import get_auth_service
from app.services.jwt import get_jwt_service
from app.services.transcript import get_transcript_service
from app.services.voice_note import get_voice_note_service

# Logging
logger = logging.getLogger("sage_whisper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Sage Whisper", version="0.1.0")
app.state.limiter = limiter


# --- Security headers middleware ---
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self'"
        )
        return response


# --- Request size limit middleware ---
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    MAX_BODY_SIZE = 105 * 1024 * 1024  # 105MB (slightly above max upload)

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_BODY_SIZE:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        return await call_next(request)


# --- Audit logging middleware ---
class AuditLogMiddleware(BaseHTTPMiddleware):
    AUDIT_PATHS = {"/api/v1/voice-notes/", "/api/v1/auth/register", "/api/v1/auth/login", "/register", "/login"}

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        # Log sensitive operations
        path = request.url.path
        method = request.method
        if method in ("POST", "DELETE") and any(path.startswith(p) for p in self.AUDIT_PATHS):
            logger.info(
                "AUDIT %s %s -> %d (%.0fms) from %s",
                method,
                path,
                response.status_code,
                duration_ms,
                request.client.host if request.client else "unknown",
            )

        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(AuditLogMiddleware)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# API routers
app.include_router(auth_router)
app.include_router(voice_notes_router)
app.include_router(transcripts_router)


# --- Rate limit error handler ---
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Handle rate limit exceeded."""
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again later."})
    return HTMLResponse(content="<h1>429</h1><p>Too many requests. Please try again later.</p>", status_code=429)


# --- Exception handler: 401 -> redirect to /login ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> HTMLResponse | RedirectResponse:
    """Handle HTTP exceptions. Redirect 401 to login for web requests."""
    if exc.status_code == 401:
        # HTMX request: send redirect header
        if request.headers.get("HX-Request"):
            response = HTMLResponse(content="", status_code=200)
            response.headers["HX-Redirect"] = "/login"
            return response
        # API request: return JSON
        if request.url.path.startswith("/api/"):
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=401, content={"detail": exc.detail})
        # Web request: redirect
        return RedirectResponse(url="/login", status_code=302)
    # All other errors: JSON for API, HTML for web
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return HTMLResponse(
        content=f"<h1>{exc.status_code}</h1><p>{exc.detail}</p>",
        status_code=exc.status_code,
    )


# --- Health check ---
@app.get("/api/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "app": "sage-whisper", "version": "0.1.0"}


# --- Web routes ---
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    """Render login page."""
    user = get_current_user_from_cookie(request)
    if user:
        return RedirectResponse(url="/", status_code=302)  # type: ignore[return-value]
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Handle login form submission."""
    auth_service = get_auth_service()
    result = auth_service.authenticate(db, email, password)

    if not result.success:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": result.error, "email": email},
        )

    jwt_service = get_jwt_service()
    token = jwt_service.create_token(
        user_id=result.user_id,  # type: ignore[arg-type]
        email=result.email,  # type: ignore[arg-type]
        display_name=result.display_name,  # type: ignore[arg-type]
    )

    response = RedirectResponse(url="/", status_code=302)
    set_auth_cookie(response, token)
    return response  # type: ignore[return-value]


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    """Render register page."""
    user = get_current_user_from_cookie(request)
    if user:
        return RedirectResponse(url="/", status_code=302)  # type: ignore[return-value]
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Handle register form submission."""
    auth_service = get_auth_service()
    result = auth_service.register(db, email, password, display_name)

    if not result.success:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": result.error, "email": email, "display_name": display_name},
        )

    jwt_service = get_jwt_service()
    token = jwt_service.create_token(
        user_id=result.user_id,  # type: ignore[arg-type]
        email=result.email,  # type: ignore[arg-type]
        display_name=result.display_name,  # type: ignore[arg-type]
    )

    response = RedirectResponse(url="/", status_code=302)
    set_auth_cookie(response, token)
    return response  # type: ignore[return-value]


@app.get("/logout")
def logout() -> RedirectResponse:
    """Clear auth cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    clear_auth_cookie(response)
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user=Depends(require_web_auth),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render dashboard page with KPIs."""
    from sqlalchemy import func

    from app.models.transcript import Transcript
    from app.models.voice_note import VoiceNote

    # KPI stats
    total_notes = db.query(func.count(VoiceNote.id)).filter(VoiceNote.user_id == user.user_id).scalar() or 0
    total_transcripts = db.query(func.count(Transcript.id)).filter(Transcript.user_id == user.user_id).scalar() or 0
    total_duration = (
        db.query(func.sum(VoiceNote.duration_seconds)).filter(VoiceNote.user_id == user.user_id).scalar() or 0
    )
    latest_note = (
        db.query(VoiceNote).filter(VoiceNote.user_id == user.user_id).order_by(VoiceNote.created_at.desc()).first()
    )

    # Recent transcripts
    tx_service = get_transcript_service()
    recent_transcripts, _ = tx_service.get_user_transcripts(db, user.user_id, limit=5)

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "user": user,
            "total_notes": total_notes,
            "total_transcripts": total_transcripts,
            "total_duration": total_duration,
            "latest_note": latest_note,
            "recent_transcripts": recent_transcripts,
        },
    )


@app.get("/upload", response_class=HTMLResponse)
def upload_page(
    request: Request,
    user=Depends(require_web_auth),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render upload page with voice note list."""
    service = get_voice_note_service()
    notes = service.get_user_voice_notes(db, user.user_id)
    return templates.TemplateResponse(
        "upload.html",
        {"request": request, "user": user, "notes": notes},
    )


@app.get("/transcripts/{transcript_id}", response_class=HTMLResponse)
def transcript_detail_page(
    request: Request,
    transcript_id: int,
    user=Depends(require_web_auth),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render transcript detail page."""
    service = get_transcript_service()
    data = service.get_transcript_with_segments(db, transcript_id, user.user_id)
    if not data:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return templates.TemplateResponse(
        "transcript_detail.html",
        {"request": request, "user": user, "transcript": data},
    )


@app.get("/partials/transcription-status/{note_id}", response_class=HTMLResponse)
def transcription_status_partial(
    request: Request,
    note_id: int,
    user=Depends(require_web_auth),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """HTMX polling partial for transcription status."""
    vn_service = get_voice_note_service()
    note = vn_service.get_voice_note(db, note_id, user.user_id)
    tx_service = get_transcript_service()
    transcript = tx_service.get_transcript_by_voice_note(db, note_id, user.user_id) if note else None
    return templates.TemplateResponse(
        "partials/transcription_status.html",
        {"request": request, "note": note, "transcript": transcript},
    )


@app.get("/transcripts", response_class=HTMLResponse)
def transcripts_list_page(
    request: Request,
    search: str | None = None,
    offset: int = 0,
    limit: int = 20,
    user=Depends(require_web_auth),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render transcripts list page."""
    tx_service = get_transcript_service()
    items, total = tx_service.get_user_transcripts(db, user.user_id, search=search, limit=limit, offset=offset)
    return templates.TemplateResponse(
        "transcripts.html",
        {
            "request": request,
            "user": user,
            "transcripts": items,
            "total": total,
            "search": search,
            "offset": offset,
            "limit": limit,
        },
    )


@app.get("/partials/transcript-rows", response_class=HTMLResponse)
def transcript_rows_partial(
    request: Request,
    search: str | None = None,
    offset: int = 0,
    limit: int = 20,
    user=Depends(require_web_auth),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """HTMX partial for transcript search results."""
    tx_service = get_transcript_service()
    items, total = tx_service.get_user_transcripts(db, user.user_id, search=search, limit=limit, offset=offset)
    return templates.TemplateResponse(
        "partials/transcript_rows.html",
        {
            "request": request,
            "transcripts": items,
            "total": total,
            "search": search,
            "offset": offset,
            "limit": limit,
        },
    )
