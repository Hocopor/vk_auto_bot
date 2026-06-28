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
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_security_headers_present(client):
    resp = await client.get("/login")
    h = resp.headers
    assert h["X-Content-Type-Options"] == "nosniff"
    # SAMEORIGIN (не DENY): нужно для превью PDF-чека в <iframe>
    assert h["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in h["Content-Security-Policy"]
    assert "default-src 'self'" in h["Content-Security-Policy"]
    assert h["Referrer-Policy"] == "same-origin"
    assert h.get("Server") == "web"


async def test_api_docs_disabled(client):
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404
    assert (await client.get("/redoc")).status_code == 404


async def test_login_rate_limited_after_5_failures(creds, client):
    login, _ = creds
    for _ in range(5):
        resp = await client.post(
            "/login",
            data={"login": login, "password": "wrong"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
    # 6-я попытка — блок 429, даже с ПРАВИЛЬНЫМ паролем (защита от брутфорса)
    resp = await client.post(
        "/login",
        data={"login": login, "password": "secret123"},
        follow_redirects=False,
    )
    assert resp.status_code == 429
    assert "session" not in resp.cookies


async def test_successful_login_resets_counter(creds, client):
    login, password = creds
    for _ in range(4):
        await client.post(
            "/login",
            data={"login": login, "password": "wrong"},
            follow_redirects=False,
        )
    # успех до достижения лимита — сбрасывает счётчик
    ok = await client.post(
        "/login",
        data={"login": login, "password": password},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    # после сброса снова можно ошибаться без немедленного бана
    again = await client.post(
        "/login",
        data={"login": login, "password": "wrong"},
        follow_redirects=False,
    )
    assert again.status_code == 401


def test_client_ip_prefers_last_forwarded():
    from app.admin.security import client_ip

    class _Req:
        def __init__(self, xff):
            self.headers = {"x-forwarded-for": xff} if xff else {}
            self.client = type("C", (), {"host": "127.0.0.1"})()

    # последний элемент = реальный пир от Caddy; первый — потенциально подделан
    assert client_ip(_Req("1.2.3.4, 9.9.9.9")) == "9.9.9.9"
    assert client_ip(_Req("")) == "127.0.0.1"
