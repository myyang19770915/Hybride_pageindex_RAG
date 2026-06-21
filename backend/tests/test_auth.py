import pytest
from app.core.config import get_settings
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def auth_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    monkeypatch.setenv("AUTH_USERS", "admin:secret:admin,alice:alicepw:user,bob:bobpw:user")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _token(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_requires_auth_when_enabled(auth_env) -> None:
    client = TestClient(app)
    assert client.get("/api/documents").status_code == 401
    bad_login = client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong"}
    )
    assert bad_login.status_code == 401


def test_document_isolation_between_users(auth_env) -> None:
    client = TestClient(app)
    alice = _token(client, "alice", "alicepw")
    bob = _token(client, "bob", "bobpw")
    admin = _token(client, "admin", "secret")

    upload = client.post(
        "/api/documents",
        files={"file": ("alice.pdf", b"%PDF-1.4\nsample", "application/pdf")},
        headers={"Authorization": f"Bearer {alice}"},
    ).json()
    document_id = upload["document_id"]

    bob_docs = client.get(
        "/api/documents", headers={"Authorization": f"Bearer {bob}"}
    ).json()
    assert document_id not in {item["document_id"] for item in bob_docs}

    bob_get = client.get(
        f"/api/documents/{document_id}", headers={"Authorization": f"Bearer {bob}"}
    )
    assert bob_get.status_code == 404

    admin_docs = client.get(
        "/api/documents", headers={"Authorization": f"Bearer {admin}"}
    ).json()
    assert document_id in {item["document_id"] for item in admin_docs}

    alice_get = client.get(
        f"/api/documents/{document_id}", headers={"Authorization": f"Bearer {alice}"}
    )
    assert alice_get.status_code == 200
    assert alice_get.json()["owner"] == "alice"
