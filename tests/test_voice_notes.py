"""Tests for voice note upload and management."""

import io

from fastapi.testclient import TestClient


class TestVoiceNoteUpload:
    """Tests for voice note upload."""

    def test_upload_valid_file(self, client: TestClient, test_user: dict, tmp_path):
        """Upload a valid audio file."""
        audio_content = b"\x00" * 1024  # 1KB dummy
        response = client.post(
            "/api/v1/voice-notes/",
            files={"file": ("test.mp3", io.BytesIO(audio_content), "audio/mpeg")},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["original_filename"] == "test.mp3"
        assert data["status"] == "uploaded"
        assert data["file_size_bytes"] == 1024

    def test_upload_invalid_extension(self, client: TestClient, test_user: dict):
        """Reject non-audio file extensions."""
        response = client.post(
            "/api/v1/voice-notes/",
            files={"file": ("test.exe", io.BytesIO(b"\x00" * 100), "application/octet-stream")},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_upload_m4a(self, client: TestClient, test_user: dict):
        """Upload an m4a file (common phone recording format)."""
        response = client.post(
            "/api/v1/voice-notes/",
            files={"file": ("recording.m4a", io.BytesIO(b"\x00" * 512), "audio/mp4")},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 200
        assert response.json()["original_filename"] == "recording.m4a"

    def test_upload_requires_auth(self, client: TestClient):
        """Upload requires authentication."""
        response = client.post(
            "/api/v1/voice-notes/",
            files={"file": ("test.mp3", io.BytesIO(b"\x00" * 100), "audio/mpeg")},
        )
        assert response.status_code == 401


class TestVoiceNoteList:
    """Tests for listing voice notes."""

    def test_list_empty(self, client: TestClient, test_user: dict):
        """List voice notes when none exist."""
        response = client.get(
            "/api/v1/voice-notes/",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_after_upload(self, client: TestClient, test_user: dict):
        """List voice notes after uploading one."""
        # Upload
        client.post(
            "/api/v1/voice-notes/",
            files={"file": ("test.mp3", io.BytesIO(b"\x00" * 256), "audio/mpeg")},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        # List
        response = client.get(
            "/api/v1/voice-notes/",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["original_filename"] == "test.mp3"


class TestVoiceNoteDelete:
    """Tests for deleting voice notes."""

    def test_delete_voice_note(self, client: TestClient, test_user: dict):
        """Delete an uploaded voice note."""
        # Upload
        upload_resp = client.post(
            "/api/v1/voice-notes/",
            files={"file": ("test.mp3", io.BytesIO(b"\x00" * 256), "audio/mpeg")},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        note_id = upload_resp.json()["id"]

        # Delete
        response = client.delete(
            f"/api/v1/voice-notes/{note_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 200
        assert response.json()["detail"] == "Voice note deleted"

        # Verify gone
        response = client.get(
            f"/api/v1/voice-notes/{note_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 404

    def test_delete_nonexistent(self, client: TestClient, test_user: dict):
        """Delete a nonexistent voice note returns 404."""
        response = client.delete(
            "/api/v1/voice-notes/9999",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 404


class TestVoiceNoteGet:
    """Tests for getting a single voice note."""

    def test_get_voice_note(self, client: TestClient, test_user: dict):
        """Get a specific voice note by ID."""
        upload_resp = client.post(
            "/api/v1/voice-notes/",
            files={"file": ("test.wav", io.BytesIO(b"\x00" * 512), "audio/wav")},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        note_id = upload_resp.json()["id"]

        response = client.get(
            f"/api/v1/voice-notes/{note_id}",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 200
        assert response.json()["original_filename"] == "test.wav"

    def test_get_nonexistent(self, client: TestClient, test_user: dict):
        """Get a nonexistent voice note returns 404."""
        response = client.get(
            "/api/v1/voice-notes/9999",
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert response.status_code == 404
