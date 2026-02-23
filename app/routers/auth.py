"""Authentication API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.rate_limit import limiter
from app.schemas.auth import ForgotPasswordRequest, LoginRequest, RegisterRequest, ResetPasswordRequest, TokenResponse
from app.services.auth import get_auth_service
from app.services.jwt import get_jwt_service

logger = logging.getLogger("sage_whisper")

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse)
@limiter.limit("5/minute")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Register a new user account."""
    auth_service = get_auth_service()
    result = auth_service.register(db, body.email, body.password, body.display_name)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    jwt_service = get_jwt_service()
    token = jwt_service.create_token(
        user_id=result.user_id,  # type: ignore[arg-type]
        email=result.email,  # type: ignore[arg-type]
        display_name=result.display_name,  # type: ignore[arg-type]
    )

    return TokenResponse(token=token, email=result.email, display_name=result.display_name)  # type: ignore[arg-type]


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate and receive a JWT token."""
    auth_service = get_auth_service()
    result = auth_service.authenticate(db, body.email, body.password)

    if not result.success:
        raise HTTPException(status_code=401, detail=result.error)

    jwt_service = get_jwt_service()
    token = jwt_service.create_token(
        user_id=result.user_id,  # type: ignore[arg-type]
        email=result.email,  # type: ignore[arg-type]
        display_name=result.display_name,  # type: ignore[arg-type]
    )

    return TokenResponse(token=token, email=result.email, display_name=result.display_name)  # type: ignore[arg-type]


@router.get("/verify")
def verify_token(token: str) -> dict:
    """Verify a JWT token and return its payload."""
    jwt_service = get_jwt_service()
    payload = jwt_service.decode_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "valid": True,
        "user_id": payload["sub"],
        "email": payload["email"],
        "display_name": payload["displayName"],
    }


@router.post("/forgot-password")
@limiter.limit("3/minute")
def forgot_password(request: Request, body: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    """Request a password reset. Logs reset link to server console."""
    auth_service = get_auth_service()
    token = auth_service.request_password_reset(db, body.email)

    if token:
        base_url = str(request.base_url).rstrip("/")
        logger.info("PASSWORD RESET: %s/reset-password?token=%s", base_url, token)

    return {
        "message": "If an account exists with that email, a reset link has been generated. Check the server console."
    }


@router.post("/reset-password")
@limiter.limit("5/minute")
def reset_password(request: Request, body: ResetPasswordRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Reset password using a valid token. Returns JWT for auto-login."""
    auth_service = get_auth_service()
    result = auth_service.reset_password(db, body.token, body.new_password)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    jwt_service = get_jwt_service()
    jwt_token = jwt_service.create_token(
        user_id=result.user_id,  # type: ignore[arg-type]
        email=result.email,  # type: ignore[arg-type]
        display_name=result.display_name,  # type: ignore[arg-type]
    )

    return TokenResponse(token=jwt_token, email=result.email, display_name=result.display_name)  # type: ignore[arg-type]
