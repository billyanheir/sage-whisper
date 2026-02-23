"""Pytest configuration and fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.transcript import Transcript, TranscriptSegment  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.voice_note import VoiceNote  # noqa: F401
from app.services.auth import AuthService


@pytest.fixture(name="db_session")
def db_session_fixture():
    """Create an in-memory SQLite database for tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def client_fixture(db_session: Session):
    """Create a test client with overridden DB dependency and disabled rate limiting."""
    from app.rate_limit import limiter
    from app.routers import voice_notes as vn_module
    from main import app

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    # Point background transcription threads at the test DB session
    vn_module._session_factory = lambda: db_session

    app.dependency_overrides[get_db] = override_get_db
    limiter.enabled = False
    with TestClient(app) as c:
        yield c
    limiter.enabled = True
    app.dependency_overrides.clear()
    vn_module._session_factory = None


@pytest.fixture(name="test_user")
def test_user_fixture(db_session: Session):
    """Create a test user and return (user_data, token)."""
    from app.services.jwt import get_jwt_service

    auth_service = AuthService()
    result = auth_service.register(db_session, "test@example.com", "password123", "Test User")

    jwt_service = get_jwt_service()
    token = jwt_service.create_token(
        user_id=result.user_id,
        email=result.email,
        display_name=result.display_name,
    )

    return {
        "user_id": result.user_id,
        "email": result.email,
        "display_name": result.display_name,
        "token": token,
    }
