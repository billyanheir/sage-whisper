"""Authentication dependencies for FastAPI routes."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.jwt import get_jwt_service

AUTH_COOKIE_NAME = "sw_auth_token"
COOKIE_MAX_AGE = 8 * 60 * 60  # 8 hours


@dataclass
class CurrentUser:
    """Authenticated user context."""

    user_id: int
    email: str
    display_name: str


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Extract and validate user from Bearer token or cookie. Raises 401 if invalid."""
    token: str | None = None

    # Check Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # Fall back to cookie
    if not token:
        token = request.cookies.get(AUTH_COOKIE_NAME)

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    jwt_service = get_jwt_service()
    payload = jwt_service.decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return CurrentUser(
        user_id=int(payload["sub"]),
        email=payload["email"],
        display_name=payload["displayName"],
    )


def get_current_user_from_cookie(request: Request) -> CurrentUser | None:
    """Extract user from cookie, return None if missing or invalid."""
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None

    jwt_service = get_jwt_service()
    payload = jwt_service.decode_token(token)
    if not payload:
        return None

    return CurrentUser(
        user_id=int(payload["sub"]),
        email=payload["email"],
        display_name=payload["displayName"],
    )


def require_web_auth(request: Request) -> CurrentUser:
    """Require authentication for web routes. Raises 401 to trigger redirect."""
    user = get_current_user_from_cookie(request)
    if not user:
        # For HTMX requests, send redirect header
        if request.headers.get("HX-Request"):
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"HX-Redirect": "/login"},
            )
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def set_auth_cookie(response: Response, token: str) -> None:
    """Set the authentication cookie."""
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=COOKIE_MAX_AGE,
    )


def clear_auth_cookie(response: Response) -> None:
    """Clear the authentication cookie."""
    response.delete_cookie(key=AUTH_COOKIE_NAME)
