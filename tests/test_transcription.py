"""Tests for transcription flow with mocked faster-whisper."""

import io
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


@dataclass
class MockSegment:
    """Mock transcription segment."""

    start: float
    end: float
    text: str


@dataclass
class MockTranscriptionInfo:
    """Mock transcription info."""

    language: str = "en"
    language_probability: float = 0.95
    duration: float = 30.0


class TestTranscriptionFlow:
    """Tests for the full transcription flow."""

    def _upload_note(self, client: TestClient, token: str) -> int:
        """Upload a test audio file and return its ID."""
        resp = client.post(
            "/api/v1/voice-notes/",
            files={"file": ("test.mp3", io.BytesIO(b"\x00" * 512), "audio/mpeg")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        return resp.json()["id"]

    @patch("app.services.transcription.TranscriptionService._get_model")
    def test_transcribe_success(self, mock_get_model, client: TestClient, test_user: dict):
        """Test successful transcription creates transcript and segments."""
        note_id = self._upload_note(client, test_user["token"])

        # Mock the whisper model
        mock_model = MagicMock()
        mock_segments = [
            MockSegment(start=0.0, end=5.0, text="Hello world"),
            MockSegment(start=5.0, end=10.0, text="This is a test"),
        ]
        mock_info = MockTranscriptionInfo()
        mock_model.transcribe.return_value = (iter(mock_segments), mock_info)
        mock_get_model.return_value = mock_model

        # Transcribe
        resp = client.post(
            f"/api/v1/voice-notes/{note_id}/transcribe",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["detail"] == "Transcription complete"
        assert "transcript_id" in data

        # Verify voice note status changed
        note_resp = client.get(
            f"/api/v1/voice-notes/{note_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert note_resp.json()["status"] == "completed"

        # Verify transcript exists
        transcript_id = data["transcript_id"]
        tx_resp = client.get(
            f"/api/v1/transcripts/{transcript_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert tx_resp.status_code == 200
        tx_data = tx_resp.json()
        assert tx_data["full_text"] == "Hello world This is a test"
        assert tx_data["language"] == "en"
        assert len(tx_data["segments"]) == 2
        assert tx_data["segments"][0]["text"] == "Hello world"
        assert tx_data["segments"][0]["start_time"] == 0.0
        assert tx_data["segments"][1]["text"] == "This is a test"

    @patch("app.services.transcription.TranscriptionService._get_model")
    def test_transcribe_creates_downloadable_text(self, mock_get_model, client: TestClient, test_user: dict):
        """Test transcript download as plain text."""
        note_id = self._upload_note(client, test_user["token"])

        mock_model = MagicMock()
        mock_segments = [MockSegment(start=0.0, end=5.0, text="Download test")]
        mock_model.transcribe.return_value = (iter(mock_segments), MockTranscriptionInfo())
        mock_get_model.return_value = mock_model

        resp = client.post(
            f"/api/v1/voice-notes/{note_id}/transcribe",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        transcript_id = resp.json()["transcript_id"]

        download_resp = client.get(
            f"/api/v1/transcripts/{transcript_id}/download",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert download_resp.status_code == 200
        assert "Download test" in download_resp.text
        assert "attachment" in download_resp.headers.get("content-disposition", "")

    def test_transcribe_nonexistent_note(self, client: TestClient, test_user: dict):
        """Transcribe a nonexistent voice note returns 404."""
        resp = client.post(
            "/api/v1/voice-notes/9999/transcribe",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 404

    @patch("app.services.transcription.TranscriptionService._get_model")
    def test_cannot_transcribe_already_completed(self, mock_get_model, client: TestClient, test_user: dict):
        """Cannot re-transcribe a completed note."""
        note_id = self._upload_note(client, test_user["token"])

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([MockSegment(start=0.0, end=1.0, text="Test")]),
            MockTranscriptionInfo(),
        )
        mock_get_model.return_value = mock_model

        # First transcription
        client.post(
            f"/api/v1/voice-notes/{note_id}/transcribe",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )

        # Second attempt should fail
        resp = client.post(
            f"/api/v1/voice-notes/{note_id}/transcribe",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 400
        assert "Cannot transcribe" in resp.json()["detail"]

    @patch("app.services.transcription.TranscriptionService._get_model")
    def test_status_transitions(self, mock_get_model, client: TestClient, test_user: dict):
        """Test voice note status transitions during transcription."""
        note_id = self._upload_note(client, test_user["token"])

        # Initially uploaded
        resp = client.get(
            f"/api/v1/voice-notes/{note_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.json()["status"] == "uploaded"

        # After transcription -> completed
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([MockSegment(start=0.0, end=1.0, text="Done")]),
            MockTranscriptionInfo(),
        )
        mock_get_model.return_value = mock_model

        client.post(
            f"/api/v1/voice-notes/{note_id}/transcribe",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )

        resp = client.get(
            f"/api/v1/voice-notes/{note_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.json()["status"] == "completed"


class TestTranscriptList:
    """Tests for transcript listing."""

    @patch("app.services.transcription.TranscriptionService._get_model")
    def test_list_transcripts(self, mock_get_model, client: TestClient, test_user: dict):
        """List transcripts returns created transcripts."""
        # Upload and transcribe
        resp = client.post(
            "/api/v1/voice-notes/",
            files={"file": ("note.mp3", io.BytesIO(b"\x00" * 256), "audio/mpeg")},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        note_id = resp.json()["id"]

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([MockSegment(start=0.0, end=1.0, text="Listed text")]),
            MockTranscriptionInfo(),
        )
        mock_get_model.return_value = mock_model

        client.post(
            f"/api/v1/voice-notes/{note_id}/transcribe",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )

        # List
        resp = client.get(
            "/api/v1/transcripts/",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "Listed text" in data["items"][0]["full_text"]

    def test_list_empty(self, client: TestClient, test_user: dict):
        """List transcripts when none exist."""
        resp = client.get(
            "/api/v1/transcripts/",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
