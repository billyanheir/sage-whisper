"""Tests for transcript file import feature."""

import io

import pytest
from fastapi.testclient import TestClient

from app.services.transcript_import import TranscriptImportService

# ---------------------------------------------------------------------------
# Parser unit tests (no DB needed)
# ---------------------------------------------------------------------------


class TestParseTxt:
    """Tests for plain text transcript parsing."""

    def test_parse_txt(self):
        """Plain text returns full text, no segments."""
        service = TranscriptImportService()
        result = service.parse_file("Hello world. This is a transcript.", "notes.txt")
        assert result.full_text == "Hello world. This is a transcript."
        assert result.segments == []
        assert result.language is None

    def test_parse_txt_empty_raises(self):
        """Empty or whitespace-only content raises ValueError."""
        service = TranscriptImportService()
        with pytest.raises(ValueError, match="empty"):
            service.parse_file("   \n\n  ", "empty.txt")


class TestParseVtt:
    """Tests for WebVTT transcript parsing."""

    def test_parse_vtt_basic(self):
        """Parse a basic WebVTT file with two segments."""
        service = TranscriptImportService()
        content = "WEBVTT\n\n00:00.000 --> 00:05.000\nHello world\n\n00:05.000 --> 00:10.000\nThis is a test\n"
        result = service.parse_file(content, "meeting.vtt")
        assert result.full_text == "Hello world This is a test"
        assert len(result.segments) == 2
        assert result.segments[0].start_time == 0.0
        assert result.segments[0].end_time == 5.0
        assert result.segments[0].text == "Hello world"
        assert result.segments[1].start_time == 5.0
        assert result.segments[1].end_time == 10.0
        assert result.segments[1].text == "This is a test"

    def test_parse_vtt_with_hours(self):
        """Parse VTT timestamps with hour component."""
        service = TranscriptImportService()
        content = "WEBVTT\n\n01:02:03.456 --> 01:02:08.789\nLong meeting segment\n"
        result = service.parse_file(content, "long.vtt")
        assert len(result.segments) == 1
        seg = result.segments[0]
        assert seg.start_time == pytest.approx(3723.456)
        assert seg.end_time == pytest.approx(3728.789)
        assert seg.text == "Long meeting segment"


class TestParseSrt:
    """Tests for SRT transcript parsing."""

    def test_parse_srt_basic(self):
        """Parse a basic SRT file with two blocks."""
        service = TranscriptImportService()
        content = "1\n00:00:00,000 --> 00:00:05,000\nHello world\n\n2\n00:00:05,000 --> 00:00:10,000\nThis is a test\n"
        result = service.parse_file(content, "subtitles.srt")
        assert result.full_text == "Hello world This is a test"
        assert len(result.segments) == 2
        assert result.segments[0].start_time == 0.0
        assert result.segments[0].end_time == 5.0
        assert result.segments[0].text == "Hello world"
        assert result.segments[1].start_time == 5.0
        assert result.segments[1].end_time == 10.0

    def test_parse_srt_strips_html(self):
        """HTML tags like <b> and <i> are removed from SRT text."""
        service = TranscriptImportService()
        content = "1\n00:00:00,000 --> 00:00:05,000\n<b>Bold text</b> and <i>italic</i>\n"
        result = service.parse_file(content, "styled.srt")
        assert result.segments[0].text == "Bold text and italic"


class TestValidateImportMetadata:
    """Tests for file metadata validation."""

    def test_validate_good_extension(self):
        """Valid extensions return None (no error)."""
        service = TranscriptImportService()
        assert service.validate_import_metadata("meeting.txt", "text/plain") is None
        assert service.validate_import_metadata("call.vtt", "text/vtt") is None
        assert service.validate_import_metadata("subtitles.srt", "text/plain") is None

    def test_validate_bad_extension(self):
        """Invalid extensions return an error message."""
        service = TranscriptImportService()
        error = service.validate_import_metadata("audio.mp3", "audio/mpeg")
        assert error is not None
        assert "Unsupported file type" in error


# ---------------------------------------------------------------------------
# API integration tests (uses client + test_user fixtures)
# ---------------------------------------------------------------------------


class TestImportApi:
    """Integration tests for the POST /api/v1/transcripts/import endpoint."""

    def _auth_headers(self, test_user: dict) -> dict:
        return {"Authorization": f"Bearer {test_user['token']}"}

    def test_import_txt(self, client: TestClient, test_user: dict):
        """Full round-trip import of a .txt file."""
        content = b"Meeting notes: we discussed the roadmap and quarterly goals."
        response = client.post(
            "/api/v1/transcripts/import",
            files={"file": ("notes.txt", io.BytesIO(content), "text/plain")},
            headers=self._auth_headers(test_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["original_filename"] == "notes.txt"
        assert data["model_size"] == "imported"
        assert data["processing_time_seconds"] == 0.0
        assert data["language"] is None
        assert "Meeting notes" in data["full_text"]
        assert data["segments"] == []

    def test_import_vtt(self, client: TestClient, test_user: dict):
        """Import a VTT file preserves segments."""
        content = b"WEBVTT\n\n00:00.000 --> 00:05.000\nFirst segment\n\n00:05.000 --> 00:10.000\nSecond segment\n"
        response = client.post(
            "/api/v1/transcripts/import",
            files={"file": ("meeting.vtt", io.BytesIO(content), "text/vtt")},
            headers=self._auth_headers(test_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["segments"]) == 2
        assert data["segments"][0]["text"] == "First segment"
        assert data["segments"][1]["text"] == "Second segment"

    def test_import_srt(self, client: TestClient, test_user: dict):
        """Import an SRT file preserves segments."""
        content = b"1\n00:00:00,000 --> 00:00:05,000\nHello world\n\n2\n00:00:05,000 --> 00:00:10,000\nGoodbye world\n"
        response = client.post(
            "/api/v1/transcripts/import",
            files={"file": ("subs.srt", io.BytesIO(content), "application/x-subrip")},
            headers=self._auth_headers(test_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["segments"]) == 2
        assert data["segments"][0]["text"] == "Hello world"

    def test_import_creates_voice_note_with_imported_status(self, client: TestClient, test_user: dict):
        """Importing creates a VoiceNote with status='imported'."""
        content = b"Some transcript text."
        client.post(
            "/api/v1/transcripts/import",
            files={"file": ("notes.txt", io.BytesIO(content), "text/plain")},
            headers=self._auth_headers(test_user),
        )

        # Check voice note was created with imported status
        vn_resp = client.get(
            "/api/v1/voice-notes/",
            headers=self._auth_headers(test_user),
        )
        assert vn_resp.status_code == 200
        items = vn_resp.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "imported"
        assert items[0]["original_filename"] == "notes.txt"

    def test_import_appears_in_transcript_list(self, client: TestClient, test_user: dict):
        """Imported transcript appears in the transcript listing."""
        content = b"Searchable meeting discussion about quarterly goals."
        client.post(
            "/api/v1/transcripts/import",
            files={"file": ("quarterly.txt", io.BytesIO(content), "text/plain")},
            headers=self._auth_headers(test_user),
        )

        # Check transcript list
        tx_resp = client.get(
            "/api/v1/transcripts/?search=quarterly",
            headers=self._auth_headers(test_user),
        )
        assert tx_resp.status_code == 200
        data = tx_resp.json()
        assert data["total"] == 1
        assert data["items"][0]["model_size"] == "imported"

    def test_import_invalid_extension(self, client: TestClient, test_user: dict):
        """Reject import of non-transcript files."""
        response = client.post(
            "/api/v1/transcripts/import",
            files={"file": ("audio.mp3", io.BytesIO(b"\x00" * 100), "audio/mpeg")},
            headers=self._auth_headers(test_user),
        )
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_import_empty_file(self, client: TestClient, test_user: dict):
        """Reject import of empty transcript file."""
        response = client.post(
            "/api/v1/transcripts/import",
            files={"file": ("empty.txt", io.BytesIO(b"   \n\n  "), "text/plain")},
            headers=self._auth_headers(test_user),
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_import_requires_auth(self, client: TestClient):
        """Import endpoint requires authentication."""
        response = client.post(
            "/api/v1/transcripts/import",
            files={"file": ("notes.txt", io.BytesIO(b"text"), "text/plain")},
        )
        assert response.status_code == 401

    def test_cannot_transcribe_imported_note(self, client: TestClient, test_user: dict):
        """Transcribe endpoint rejects imported voice notes."""
        content = b"Already transcribed content."
        import_resp = client.post(
            "/api/v1/transcripts/import",
            files={"file": ("notes.txt", io.BytesIO(content), "text/plain")},
            headers=self._auth_headers(test_user),
        )
        voice_note_id = import_resp.json()["voice_note_id"]

        # Try to transcribe the imported note
        response = client.post(
            f"/api/v1/voice-notes/{voice_note_id}/transcribe",
            headers=self._auth_headers(test_user),
        )
        assert response.status_code == 400
        assert "Cannot transcribe" in response.json()["detail"]
