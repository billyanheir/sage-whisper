"""JWT Token Service."""

from datetime import datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from app.config import get_settings


class JWTService:
    """Handles JWT token creation and validation."""

    def __init__(self) -> None:
        settings = get_settings()
        self.secret_key = settings.JWT_SECRET_KEY
        self.algorithm = settings.JWT_ALGORITHM
        self.expire_minutes = settings.JWT_EXPIRE_MINUTES

    def create_token(self, user_id: int, email: str, display_name: str) -> str:
        """Create a JWT token for the given user."""
        expire = datetime.utcnow() + timedelta(minutes=self.expire_minutes)
        payload = {
            "sub": str(user_id),
            "email": email,
            "displayName": display_name,
            "exp": expire,
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode_token(self, token: str) -> dict[str, Any] | None:
        """Decode and validate a JWT token. Returns None if invalid."""
        try:
            return jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except JWTError:
            return None

    def is_token_valid(self, token: str) -> bool:
        """Check if a token is valid."""
        return self.decode_token(token) is not None


_jwt_service: JWTService | None = None


def get_jwt_service() -> JWTService:
    """Get singleton JWT service instance."""
    global _jwt_service
    if _jwt_service is None:
        _jwt_service = JWTService()
    return _jwt_service
