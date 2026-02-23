"""Tests for authentication endpoints and flows."""

from fastapi.testclient import TestClient


class TestRegistration:
    """Tests for user registration."""

    def test_register_api_success(self, client: TestClient):
        """Register a new user via API."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": "password123", "display_name": "New User"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "new@example.com"
        assert data["display_name"] == "New User"
        assert "token" in data

    def test_register_api_duplicate_email(self, client: TestClient, test_user: dict):
        """Reject duplicate email registration."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "password123", "display_name": "Another User"},
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    def test_register_web_success(self, client: TestClient):
        """Register via web form redirects to dashboard."""
        response = client.post(
            "/register",
            data={"email": "web@example.com", "password": "password123", "display_name": "Web User"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/"

    def test_register_web_duplicate(self, client: TestClient, test_user: dict):
        """Web registration with duplicate email shows error."""
        response = client.post(
            "/register",
            data={"email": "test@example.com", "password": "password123", "display_name": "Dup User"},
        )
        assert response.status_code == 200
        assert "already registered" in response.text


class TestLogin:
    """Tests for user login."""

    def test_login_api_success(self, client: TestClient, test_user: dict):
        """Login via API with valid credentials."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert "token" in data

    def test_login_api_wrong_password(self, client: TestClient, test_user: dict):
        """Reject login with wrong password."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "wrongpassword"},
        )
        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]

    def test_login_api_nonexistent_email(self, client: TestClient):
        """Reject login with unknown email."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "password123"},
        )
        assert response.status_code == 401

    def test_login_web_success(self, client: TestClient, test_user: dict):
        """Web login redirects to dashboard and sets cookie."""
        response = client.post(
            "/login",
            data={"email": "test@example.com", "password": "password123"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/"
        assert "sw_auth_token" in response.cookies

    def test_login_web_failure(self, client: TestClient, test_user: dict):
        """Web login with wrong password shows error."""
        response = client.post(
            "/login",
            data={"email": "test@example.com", "password": "wrong"},
        )
        assert response.status_code == 200
        assert "Invalid" in response.text

    def test_login_case_insensitive(self, client: TestClient, test_user: dict):
        """Login works regardless of email case."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "TEST@EXAMPLE.COM", "password": "password123"},
        )
        assert response.status_code == 200


class TestTokenVerification:
    """Tests for token verification."""

    def test_verify_valid_token(self, client: TestClient, test_user: dict):
        """Verify a valid token returns payload."""
        response = client.get(f"/api/v1/auth/verify?token={test_user['token']}")
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["email"] == "test@example.com"
        assert data["display_name"] == "Test User"

    def test_verify_invalid_token(self, client: TestClient):
        """Reject an invalid token."""
        response = client.get("/api/v1/auth/verify?token=invalid.token.here")
        assert response.status_code == 401


class TestProtectedRoutes:
    """Tests for authentication-protected routes."""

    def test_dashboard_requires_auth(self, client: TestClient):
        """Dashboard redirects unauthenticated users to login."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers["location"]

    def test_dashboard_with_cookie(self, client: TestClient, test_user: dict):
        """Dashboard accessible with valid auth cookie."""
        client.cookies.set("sw_auth_token", test_user["token"])
        response = client.get("/")
        assert response.status_code == 200
        assert "Welcome back" in response.text

    def test_login_page_redirects_authenticated(self, client: TestClient, test_user: dict):
        """Login page redirects already-authenticated users to dashboard."""
        client.cookies.set("sw_auth_token", test_user["token"])
        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/"

    def test_register_page_redirects_authenticated(self, client: TestClient, test_user: dict):
        """Register page redirects already-authenticated users to dashboard."""
        client.cookies.set("sw_auth_token", test_user["token"])
        response = client.get("/register", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/"

    def test_logout_clears_cookie(self, client: TestClient, test_user: dict):
        """Logout clears auth cookie and redirects to login."""
        client.cookies.set("sw_auth_token", test_user["token"])
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers["location"]


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check(self, client: TestClient):
        """Health check returns ok status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app"] == "sage-whisper"
