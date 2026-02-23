"""Authentication service."""

from dataclasses import dataclass
from datetime import datetime

import bcrypt
from sqlalchemy.orm import Session

from app.models.user import User


@dataclass
class AuthResult:
    """Result of an authentication attempt."""

    success: bool
    error: str | None = None
    user_id: int | None = None
    email: str | None = None
    display_name: str | None = None


class AuthService:
    """Handles user registration and authentication."""

    def register(self, db: Session, email: str, password: str, display_name: str) -> AuthResult:
        """Register a new user. Returns AuthResult with success/error."""
        existing = db.query(User).filter(User.email.ilike(email)).first()
        if existing:
            return AuthResult(success=False, error="Email already registered")

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user = User(
            email=email.lower().strip(),
            password_hash=password_hash,
            display_name=display_name.strip(),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        return AuthResult(
            success=True,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
        )

    def authenticate(self, db: Session, email: str, password: str) -> AuthResult:
        """Authenticate a user by email and password."""
        user = db.query(User).filter(User.email.ilike(email)).first()
        if not user:
            return AuthResult(success=False, error="Invalid email or password")

        if not user.is_active:
            return AuthResult(success=False, error="Account is deactivated")

        if not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
            return AuthResult(success=False, error="Invalid email or password")

        user.last_login_at = datetime.utcnow()
        db.commit()

        return AuthResult(
            success=True,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
        )


_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """Get singleton auth service instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
