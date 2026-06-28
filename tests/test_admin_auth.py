import httpx
import pytest
from passlib.context import CryptContext

from app.admin.main import app
from app.core.config import settings

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password_hash", pwd.hash("secret123"))
    return ("admin", "secret123")


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    # https — cookie сессии теперь Secure (https_only=True), по http не вернётся
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


async def test_login_page_renders(client):
    resp = await client.get("/login")
    assert resp.status_code == 200
    assert 'name="password"' in resp.text


async def test_login_success(creds, client):
    login, password = creds
    resp = await client.post(
        "/login",
        data={"login": login, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert "session" in resp.cookies


async def test_login_failure(creds, client):
    login, _ = creds
    resp = await client.post(
        "/login",
        data={"login": login, "password": "wrong-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "Неверный логин или пароль" in resp.text


async def test_protected_redirects_when_anonymous(client):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


async def test_protected_accessible_after_login(creds, client):
    login, password = creds
    login_resp = await client.post(
        "/login",
        data={"login": login, "password": password},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303

    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Мероприятия" in resp.text


async def test_logout(creds, client):
    login, password = creds
    await client.post(
        "/login",
        data={"login": login, "password": password},
        follow_redirects=False,
    )

    logout_resp = await client.get("/logout", follow_redirects=False)
    assert logout_resp.status_code == 303
    assert logout_resp.headers["location"] == "/login"

    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
