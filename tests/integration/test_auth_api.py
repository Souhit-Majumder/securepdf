import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database.database import init_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield

def random_user():
    uid = uuid.uuid4().hex[:8]
    return {
        "email": f"user_{uid}@example.com",
        "username": f"user_{uid}",
        "password": "StrongPassword123!"
    }

def test_register_success():
    data = random_user()
    res = client.post("/api/auth/register", json=data)
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == data["email"]
    assert body["username"] == data["username"]
    assert "id" in body
    assert "created_at" in body
    assert "password_hash" not in body
    assert "salt" not in body
    assert "password" not in body
    # Cookie should be set
    assert "securepdf_session" in res.cookies

def test_register_duplicate_email():
    data = random_user()
    res1 = client.post("/api/auth/register", json=data)
    assert res1.status_code == 201

    # Attempt registration with duplicate email
    dup = random_user()
    dup["email"] = data["email"]
    res2 = client.post("/api/auth/register", json=dup)
    assert res2.status_code == 409
    assert "email" in res2.json()["detail"].lower()

def test_register_duplicate_username():
    data = random_user()
    res1 = client.post("/api/auth/register", json=data)
    assert res1.status_code == 201

    # Attempt registration with duplicate username
    dup = random_user()
    dup["username"] = data["username"]
    res2 = client.post("/api/auth/register", json=dup)
    assert res2.status_code == 409
    assert "username" in res2.json()["detail"].lower()

def test_register_validation_errors():
    # Invalid email
    res1 = client.post("/api/auth/register", json={
        "email": "not-an-email",
        "username": "valid_user",
        "password": "Password123!"
    })
    assert res1.status_code == 422

    # Password too short (<8)
    res2 = client.post("/api/auth/register", json={
        "email": "valid@example.com",
        "username": "valid_user",
        "password": "123"
    })
    assert res2.status_code == 422

    # Invalid username (too short)
    res3 = client.post("/api/auth/register", json={
        "email": "valid@example.com",
        "username": "a",
        "password": "Password123!"
    })
    assert res3.status_code == 422

def test_login_with_email_and_username():
    data = random_user()
    reg = client.post("/api/auth/register", json=data)
    assert reg.status_code == 201

    # Login with email
    res_email = client.post("/api/auth/login", json={
        "identifier": data["email"],
        "password": data["password"]
    })
    assert res_email.status_code == 200
    assert res_email.json()["email"] == data["email"]
    assert "securepdf_session" in res_email.cookies

    # Login with username
    res_user = client.post("/api/auth/login", json={
        "identifier": data["username"],
        "password": data["password"]
    })
    assert res_user.status_code == 200
    assert res_user.json()["username"] == data["username"]
    assert "securepdf_session" in res_user.cookies

def test_login_invalid_credentials():
    data = random_user()
    reg = client.post("/api/auth/register", json=data)
    assert reg.status_code == 201

    # Wrong password
    res1 = client.post("/api/auth/login", json={
        "identifier": data["email"],
        "password": "WrongPassword123"
    })
    assert res1.status_code == 401

    # Non-existent user
    res2 = client.post("/api/auth/login", json={
        "identifier": "nonexistent_user_99999",
        "password": "SomePassword123"
    })
    assert res2.status_code == 401

def test_session_lifecycle_and_logout():
    data = random_user()
    reg = client.post("/api/auth/register", json=data)
    assert reg.status_code == 201
    session_cookie = reg.cookies.get("securepdf_session")
    assert session_cookie is not None

    # Verify session via /me
    me_res = client.get("/api/auth/me", cookies={"securepdf_session": session_cookie})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == data["email"]

    # Logout
    logout_res = client.post("/api/auth/logout", cookies={"securepdf_session": session_cookie})
    assert logout_res.status_code == 200

    # Subsequent /me should fail with 401
    me_after_logout = client.get("/api/auth/me", cookies={"securepdf_session": session_cookie})
    assert me_after_logout.status_code == 401

def test_me_unauthenticated():
    res = client.get("/api/auth/me")
    assert res.status_code == 401
