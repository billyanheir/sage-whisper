"""Authentication API endpoints."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.rate_limit import limiter
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.services.auth import get_auth_service
from app.services.jwt import get_jwt_service

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse)
@limiter.limit("5/minute")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Register a new user account."""
    auth_service = get_auth_service()
    result = auth_service.register(db, body.email, body.password, body.display_name)

    if not result.success:
        from fastapi import HTTPException

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
        from fastapi import HTTPException

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
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "valid": True,
        "user_id": payload["sub"],
        "email": payload["email"],
        "display_name": payload["displayName"],
    }
