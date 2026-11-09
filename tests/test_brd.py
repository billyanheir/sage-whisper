"""Tests for BRD generation, review, and export."""

import json
import time
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.brd import BRD, BRDRequirement
from app.models.transcript import Transcript
from app.models.voice_note import VoiceNote


@dataclass
class MockSegment:
    start: float
    end: float
    text: str


@dataclass
class MockTranscriptionInfo:
    language: str = "en"
    language_probability: float = 0.95
    duration: float = 30.0


MOCK_OLLAMA_RESPONSE = json.dumps(
    [
        {"requirement": "The system must support user authentication", "category": "Security", "priority": "must"},
        {"requirement": "The system should display a dashboard", "category": "UI/UX", "priority": "should"},
        {"requirement": "The system could send email notifications", "category": "Functional", "priority": "could"},
    ]
)

MOCK_SPLIT_RESPONSE = json.dumps(
    [
        {
            "requirement": "The system must support login with email and password",
            "category": "Security",
            "priority": "must",
        },
        {"requirement": "The system must support password reset", "category": "Security", "priority": "must"},
    ]
)


def _create_transcript(db_session: Session, user_id: int) -> tuple[int, int]:
    """Create a voice note + transcript directly in the DB. Returns (note_id, transcript_id)."""
    note = VoiceNote(
        user_id=user_id,
        original_filename="meeting.mp3",
        stored_filename=f"test_{user_id}_{time.time()}.mp3",
        file_size_bytes=256,
        mime_type="audio/mpeg",
        status="completed",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(note)
    db_session.commit()
    db_session.refresh(note)

    transcript = Transcript(
        voice_note_id=note.id,
        user_id=user_id,
        full_text="We need to build a login system with email auth. Also we need a dashboard that shows KPIs. It would be nice to have email notifications.",
        language="en",
        model_size="base",
        processing_time_seconds=5.0,
        created_at=datetime.utcnow(),
    )
    db_session.add(transcript)
    db_session.commit()
    db_session.refresh(transcript)

    return note.id, transcript.id


def _create_brd_with_requirements(db_session: Session, user_id: int, transcript_id: int, status: str = "review") -> int:
    """Create a BRD with requirements directly in DB. Returns brd_id."""
    brd = BRD(
        transcript_id=transcript_id,
        user_id=user_id,
        title="BRD - meeting.mp3",
        status=status,
        created_at=datetime.utcnow(),
        finalized_at=datetime.utcnow() if status == "finalized" else None,
    )
    db_session.add(brd)
    db_session.commit()
    db_session.refresh(brd)

    requirements_data = [
        ("The system must support user authentication", "Security", "must"),
        ("The system should display a dashboard", "UI/UX", "should"),
        ("The system could send email notifications", "Functional", "could"),
    ]
    for i, (text, category, priority) in enumerate(requirements_data):
        req = BRDRequirement(
            brd_id=brd.id,
            requirement_text=text,
            category=category,
            priority=priority,
            status="pending",
            sort_order=i,
            created_at=datetime.utcnow(),
        )
        db_session.add(req)

    db_session.commit()
    return brd.id


def _generate_brd_with_mock(
    client: TestClient,
    token: str,
    transcript_id: int,
    parent_brd_id: int | None = None,
    project_context: str | None = None,
    github_repo_url: str | None = None,
) -> int:
    """Generate a BRD via API with mocked Ollama. Returns brd_id."""
    with patch("app.services.brd.BRDService._call_ollama") as mock_ollama:
        mock_ollama.return_value = MOCK_OLLAMA_RESPONSE

        params: dict = {"transcript_id": transcript_id}
        if parent_brd_id:
            params["parent_brd_id"] = parent_brd_id
        if project_context:
            params["project_context"] = project_context
        if github_repo_url:
            params["github_repo_url"] = github_repo_url

        resp = client.post(
            "/api/v1/brd/generate",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        brd_id = resp.json()["brd_id"]

        # Wait for background generation to complete
        deadline = time.time() + 5
        while time.time() < deadline:
            brd_resp = client.get(
                f"/api/v1/brd/{brd_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if brd_resp.json()["status"] != "generating":
                break
            time.sleep(0.1)

    return brd_id


class TestBRDGeneration:
    """Tests for BRD generation from transcript."""

    def test_generate_brd(self, client: TestClient, test_user: dict, db_session: Session):
        """Generate BRD from transcript with mocked Ollama."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _generate_brd_with_mock(client, test_user["token"], transcript_id)

        resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "review"
        assert len(data["requirements"]) == 3
        assert data["requirements"][0]["requirement_text"] == "The system must support user authentication"

    def test_generate_brd_with_project_context(self, client: TestClient, test_user: dict, db_session: Session):
        """Generate BRD with project context text."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])

        with patch("app.services.brd.BRDService._call_ollama") as mock_ollama:
            mock_ollama.return_value = MOCK_OLLAMA_RESPONSE

            resp = client.post(
                "/api/v1/brd/generate",
                params={
                    "transcript_id": transcript_id,
                    "project_context": "This is a web app built with FastAPI and React.",
                },
                headers={"Authorization": f"Bearer {test_user['token']}"},
            )
            assert resp.status_code == 200
            brd_id = resp.json()["brd_id"]

            # Wait for completion
            deadline = time.time() + 5
            while time.time() < deadline:
                brd_resp = client.get(
                    f"/api/v1/brd/{brd_id}",
                    headers={"Authorization": f"Bearer {test_user['token']}"},
                )
                if brd_resp.json()["status"] != "generating":
                    break
                time.sleep(0.1)

        brd_resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert brd_resp.json()["project_context"] == "This is a web app built with FastAPI and React."

    def test_generate_brd_with_existing_brd_context(self, client: TestClient, test_user: dict, db_session: Session):
        """Generate BRD building on an existing finalized BRD."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])

        # Create parent BRD directly in DB
        parent_brd_id = _create_brd_with_requirements(
            db_session, test_user["user_id"], transcript_id, status="finalized"
        )

        # Approve parent requirements so they serve as context
        parent_reqs = db_session.query(BRDRequirement).filter(BRDRequirement.brd_id == parent_brd_id).all()
        for req in parent_reqs:
            req.status = "approved"
        db_session.commit()

        # Generate child BRD referencing parent
        child_id = _generate_brd_with_mock(client, test_user["token"], transcript_id, parent_brd_id=parent_brd_id)

        child_resp = client.get(
            f"/api/v1/brd/{child_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert child_resp.json()["parent_brd_id"] == parent_brd_id
        assert child_resp.json()["status"] == "review"

    def test_generate_brd_transcript_not_found(self, client: TestClient, test_user: dict):
        """Cannot generate BRD for nonexistent transcript."""
        resp = client.post(
            "/api/v1/brd/generate",
            params={"transcript_id": 99999},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 404


class TestBRDRetrieval:
    """Tests for BRD retrieval."""

    def test_get_brd(self, client: TestClient, test_user: dict, db_session: Session):
        """Get BRD with requirements."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == brd_id
        assert "requirements" in data
        assert len(data["requirements"]) == 3

    def test_get_brd_not_found(self, client: TestClient, test_user: dict):
        """Cannot get nonexistent BRD."""
        resp = client.get(
            "/api/v1/brd/99999",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 404

    def test_get_brd_auth_required(self, client: TestClient, test_user: dict, db_session: Session):
        """Cannot access BRD belonging to another user."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        # Create second user
        from app.services.auth import AuthService
        from app.services.jwt import get_jwt_service

        auth_service = AuthService()
        result = auth_service.register(db_session, "other@example.com", "password123", "Other User")
        jwt_service = get_jwt_service()
        other_token = jwt_service.create_token(result.user_id, result.email, result.display_name)

        resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404


class TestRequirementUpdates:
    """Tests for requirement approve/edit/reject."""

    def test_approve_requirement(self, client: TestClient, test_user: dict, db_session: Session):
        """Approve a requirement."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        brd_resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        req_id = brd_resp.json()["requirements"][0]["id"]

        resp = client.patch(
            f"/api/v1/brd/{brd_id}/requirements/{req_id}",
            json={"status": "approved"},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_edit_requirement(self, client: TestClient, test_user: dict, db_session: Session):
        """Edit a requirement's text."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        brd_resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        req_id = brd_resp.json()["requirements"][0]["id"]

        resp = client.patch(
            f"/api/v1/brd/{brd_id}/requirements/{req_id}",
            json={"requirement_text": "Updated requirement text", "status": "edited"},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["requirement_text"] == "Updated requirement text"
        assert resp.json()["status"] == "edited"

    def test_reject_requirement(self, client: TestClient, test_user: dict, db_session: Session):
        """Reject a requirement."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        brd_resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        req_id = brd_resp.json()["requirements"][0]["id"]

        resp = client.patch(
            f"/api/v1/brd/{brd_id}/requirements/{req_id}",
            json={"status": "rejected"},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_update_requirement_not_found(self, client: TestClient, test_user: dict, db_session: Session):
        """Cannot update nonexistent requirement."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        resp = client.patch(
            f"/api/v1/brd/{brd_id}/requirements/99999",
            json={"status": "approved"},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 404


class TestRequirementSplit:
    """Tests for splitting requirements."""

    def test_split_requirement(self, client: TestClient, test_user: dict, db_session: Session):
        """Split a requirement into sub-requirements."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        brd_resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        req_id = brd_resp.json()["requirements"][0]["id"]

        with patch("app.services.brd.BRDService._call_ollama") as mock_ollama:
            mock_ollama.return_value = MOCK_SPLIT_RESPONSE

            resp = client.post(
                f"/api/v1/brd/{brd_id}/requirements/{req_id}/split",
                headers={"Authorization": f"Bearer {test_user['token']}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["requirements"]) == 2
            assert "login with email" in data["requirements"][0]["requirement_text"]

        # Verify parent is now rejected
        brd_resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        parent_req = next(r for r in brd_resp.json()["requirements"] if r["id"] == req_id)
        assert parent_req["status"] == "rejected"


class TestBRDFinalize:
    """Tests for finalizing a BRD."""

    def test_finalize_brd(self, client: TestClient, test_user: dict, db_session: Session):
        """Finalize a BRD after reviewing all requirements."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        # Approve all requirements
        brd_resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        for req in brd_resp.json()["requirements"]:
            client.patch(
                f"/api/v1/brd/{brd_id}/requirements/{req['id']}",
                json={"status": "approved"},
                headers={"Authorization": f"Bearer {test_user['token']}"},
            )

        # Finalize
        resp = client.post(
            f"/api/v1/brd/{brd_id}/finalize",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "finalized"
        assert resp.json()["finalized_at"] is not None

    def test_finalize_brd_not_found(self, client: TestClient, test_user: dict):
        """Cannot finalize nonexistent BRD."""
        resp = client.post(
            "/api/v1/brd/99999/finalize",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 404


class TestBRDDownload:
    """Tests for Markdown download."""

    def test_download_markdown(self, client: TestClient, test_user: dict, db_session: Session):
        """Download BRD as Markdown."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        # Approve some requirements
        brd_resp = client.get(
            f"/api/v1/brd/{brd_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        for req in brd_resp.json()["requirements"][:2]:
            client.patch(
                f"/api/v1/brd/{brd_id}/requirements/{req['id']}",
                json={"status": "approved"},
                headers={"Authorization": f"Bearer {test_user['token']}"},
            )

        # Finalize
        client.post(
            f"/api/v1/brd/{brd_id}/finalize",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )

        # Download
        resp = client.get(
            f"/api/v1/brd/{brd_id}/download",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        text = resp.text
        assert "BRD - meeting.mp3" in text
        assert "user authentication" in text
        assert "content-disposition" in resp.headers
        assert ".md" in resp.headers["content-disposition"]

    def test_download_not_found(self, client: TestClient, test_user: dict):
        """Cannot download nonexistent BRD."""
        resp = client.get(
            "/api/v1/brd/99999/download",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 404


class TestBRDWebPages:
    """Tests for BRD web page rendering."""

    def test_context_form_page(self, client: TestClient, test_user: dict, db_session: Session):
        """Context form page renders."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])

        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get(f"/brd/generate/{transcript_id}")
        assert resp.status_code == 200
        assert "Generate BRD" in resp.text
        assert "meeting.mp3" in resp.text

    def test_context_form_transcript_not_found(self, client: TestClient, test_user: dict):
        """Context form returns 404 for nonexistent transcript."""
        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get("/brd/generate/99999")
        assert resp.status_code == 404

    def test_review_page(self, client: TestClient, test_user: dict, db_session: Session):
        """Review wizard page renders."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get(f"/brd/{brd_id}/review")
        assert resp.status_code == 200
        assert "Review" in resp.text or "review" in resp.text

    def test_final_page(self, client: TestClient, test_user: dict, db_session: Session):
        """Final BRD page renders."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id, status="finalized")

        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get(f"/brd/{brd_id}")
        assert resp.status_code == 200
        assert "BRD" in resp.text

    def test_brd_status_partial(self, client: TestClient, test_user: dict, db_session: Session):
        """BRD status polling partial works."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])
        brd_id = _create_brd_with_requirements(db_session, test_user["user_id"], transcript_id)

        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get(f"/partials/brd-status/{brd_id}")
        assert resp.status_code == 200

    def test_web_form_generates_brd(self, client: TestClient, test_user: dict, db_session: Session):
        """Web form POST generates a BRD and redirects to review."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])

        client.cookies.set("sw_auth_token", test_user["token"])

        with patch("app.services.brd.BRDService._call_ollama") as mock_ollama:
            mock_ollama.return_value = MOCK_OLLAMA_RESPONSE

            resp = client.post(
                f"/brd/generate/{transcript_id}",
                data={
                    "parent_brd_id": "0",
                    "project_context": "Test project",
                    "github_repo_url": "",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert "/brd/" in resp.headers["location"]
            assert "/review" in resp.headers["location"]

    def test_transcript_detail_has_brd_button(self, client: TestClient, test_user: dict, db_session: Session):
        """Transcript detail page has Generate BRD button."""
        _, transcript_id = _create_transcript(db_session, test_user["user_id"])

        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get(f"/transcripts/{transcript_id}")
        assert resp.status_code == 200
        assert "Generate BRD" in resp.text
        assert f"/brd/generate/{transcript_id}" in resp.text
