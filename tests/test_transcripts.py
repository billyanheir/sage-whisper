"""Tests for transcript list, search, pagination, and dashboard."""

import io
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


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


def _upload_and_transcribe(client: TestClient, token: str, filename: str, text: str) -> tuple[int, int]:
    """Upload a file and transcribe it. Returns (note_id, transcript_id)."""
    resp = client.post(
        "/api/v1/voice-notes/",
        files={"file": (filename, io.BytesIO(b"\x00" * 256), "audio/mpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    note_id = resp.json()["id"]

    with patch("app.services.transcription.TranscriptionService._get_model") as mock_get_model:
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([MockSegment(start=0.0, end=5.0, text=text)]),
            MockTranscriptionInfo(),
        )
        mock_get_model.return_value = mock_model

        resp = client.post(
            f"/api/v1/voice-notes/{note_id}/transcribe",
            headers={"Authorization": f"Bearer {token}"},
        )
        transcript_id = resp.json()["transcript_id"]

    return note_id, transcript_id


class TestTranscriptSearch:
    """Tests for transcript search functionality."""

    def test_search_by_text(self, client: TestClient, test_user: dict):
        """Search transcripts by text content."""
        _upload_and_transcribe(client, test_user["token"], "meeting.mp3", "Quarterly budget review")
        _upload_and_transcribe(client, test_user["token"], "note.mp3", "Grocery list for tomorrow")

        # Search for "budget"
        resp = client.get(
            "/api/v1/transcripts/?search=budget",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "budget" in data["items"][0]["full_text"].lower()

    def test_search_no_results(self, client: TestClient, test_user: dict):
        """Search with no matching results."""
        _upload_and_transcribe(client, test_user["token"], "note.mp3", "Hello world")

        resp = client.get(
            "/api/v1/transcripts/?search=nonexistent",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_search_case_insensitive(self, client: TestClient, test_user: dict):
        """Search is case-insensitive."""
        _upload_and_transcribe(client, test_user["token"], "note.mp3", "Important Meeting Notes")

        resp = client.get(
            "/api/v1/transcripts/?search=important",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


class TestTranscriptPagination:
    """Tests for transcript pagination."""

    def test_pagination_limit(self, client: TestClient, test_user: dict):
        """Pagination respects limit parameter."""
        for i in range(3):
            _upload_and_transcribe(client, test_user["token"], f"note{i}.mp3", f"Text {i}")

        resp = client.get(
            "/api/v1/transcripts/?limit=2",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2

    def test_pagination_offset(self, client: TestClient, test_user: dict):
        """Pagination respects offset parameter."""
        for i in range(3):
            _upload_and_transcribe(client, test_user["token"], f"note{i}.mp3", f"Text {i}")

        resp = client.get(
            "/api/v1/transcripts/?limit=2&offset=2",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 1


class TestTranscriptDownload:
    """Tests for transcript download."""

    def test_download_format(self, client: TestClient, test_user: dict):
        """Download contains expected format with timestamps."""
        _, transcript_id = _upload_and_transcribe(client, test_user["token"], "meeting.mp3", "Hello world")

        resp = client.get(
            f"/api/v1/transcripts/{transcript_id}/download",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        text = resp.text
        assert "meeting.mp3" in text
        assert "[00:00]" in text
        assert "Hello world" in text
        assert "content-disposition" in resp.headers
        assert "meeting.txt" in resp.headers["content-disposition"]


class TestDashboard:
    """Tests for dashboard KPIs."""

    def test_dashboard_empty(self, client: TestClient, test_user: dict):
        """Dashboard shows zero stats with no data."""
        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Welcome back" in resp.text

    def test_dashboard_with_data(self, client: TestClient, test_user: dict):
        """Dashboard shows KPI stats after transcription."""
        _upload_and_transcribe(client, test_user["token"], "note.mp3", "Dashboard test")

        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert "Voice Notes" in html
        assert "Transcripts" in html


class TestTranscriptsWebPage:
    """Tests for the transcripts list web page."""

    def test_transcripts_page_loads(self, client: TestClient, test_user: dict):
        """Transcripts page loads with auth."""
        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get("/transcripts")
        assert resp.status_code == 200
        assert "Transcripts" in resp.text

    def test_transcript_rows_partial(self, client: TestClient, test_user: dict):
        """HTMX partial for transcript rows works."""
        _upload_and_transcribe(client, test_user["token"], "note.mp3", "Partial test text")

        client.cookies.set("sw_auth_token", test_user["token"])
        resp = client.get("/partials/transcript-rows?search=partial")
        assert resp.status_code == 200
        assert "Partial test text" in resp.text
