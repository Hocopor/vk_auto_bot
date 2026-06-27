import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.deps import get_session, require_login
from app.admin.main import app
from app.admin.routes import settings as settings_routes
from app.bot import vk_check
from app.core import crypto
from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.config import settings
from app.core.db import Base
from app.core.models import AppSetting
from app.core.services import app_settings as s


@pytest.fixture(autouse=True)
def _secrets_key(monkeypatch):
    monkeypatch.setattr(settings, "secrets_key", Fernet.generate_key().decode())


def test_crypto_roundtrip():
    assert crypto.decrypt(crypto.encrypt("привет-123")) == "привет-123"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
    await engine.dispose()


async def test_set_get_plain(session):
    await s.set_setting(session, s.KEY_VK_GROUP_ID, "456")
    await session.commit()
    assert await s.get_setting(session, s.KEY_VK_GROUP_ID) == "456"


async def test_set_get_secret_encrypted(session):
    await s.set_setting(session, s.KEY_VK_TOKEN, "supersecret")
    await session.commit()
    assert await s.get_setting(session, s.KEY_VK_TOKEN) == "supersecret"
    row = await session.get(AppSetting, s.KEY_VK_TOKEN)
    assert row.value != "supersecret"


async def test_set_empty_clears(session):
    await s.set_setting(session, s.KEY_VK_GROUP_ID, "")
    await session.commit()
    assert await s.get_setting(session, s.KEY_VK_GROUP_ID) is None
    assert await s.is_set(session, s.KEY_VK_GROUP_ID) is False


async def test_is_set(session):
    await s.set_setting(session, s.KEY_VK_TOKEN, "tok")
    await session.commit()
    assert await s.is_set(session, s.KEY_VK_TOKEN) is True


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def client(maker):
    async def _get_session_override():
        async with maker() as sess:
            yield sess

    async def _require_login_override():
        return "admin"

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[require_login] = _require_login_override

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_login, None)


async def test_settings_page_get(client):
    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "Настройки" in resp.text


async def test_settings_save(client, maker):
    resp = await client.post(
        "/settings",
        data={"vk_token": "tok123", "vk_group_id": "789"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "сохранены" in resp.text

    async with maker() as sess:
        assert await s.get_setting(sess, s.KEY_VK_GROUP_ID) == "789"
        assert await s.get_setting(sess, s.KEY_VK_TOKEN) == "tok123"


async def test_settings_token_not_overwritten_when_empty(client, maker):
    await client.post(
        "/settings",
        data={"vk_token": "tok123", "vk_group_id": "1"},
        follow_redirects=False,
    )
    await client.post(
        "/settings",
        data={"vk_token": "", "vk_group_id": "2"},
        follow_redirects=False,
    )
    async with maker() as sess:
        assert await s.get_setting(sess, s.KEY_VK_TOKEN) == "tok123"
        assert await s.get_setting(sess, s.KEY_VK_GROUP_ID) == "2"


async def test_settings_token_masked_in_html(client):
    await client.post(
        "/settings",
        data={"vk_token": "tok123", "vk_group_id": ""},
        follow_redirects=False,
    )
    resp = await client.get("/settings")
    assert "tok123" not in resp.text
    assert "оставьте пустым" in resp.text


async def test_settings_abuse_gate_save(client, maker):
    resp = await client.post(
        "/settings",
        data={
            "vk_group_id": "1",
            "receipt_max_age_days": "7",
            "autoconfirm_without_date": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    async with maker() as sess:
        assert await s.get_setting(sess, s.KEY_RECEIPT_MAX_AGE_DAYS) == "7"
        assert await s.get_setting(sess, s.KEY_AUTOCONFIRM_WITHOUT_DATE) == "true"


async def test_settings_page_has_abuse_fields(client):
    resp = await client.get("/settings")
    assert 'name="receipt_max_age_days"' in resp.text
    assert 'name="autoconfirm_without_date"' in resp.text


async def test_test_vk_endpoint(client, monkeypatch):
    async def fake_test_vk(token, group_id=None):
        return True, "VK OK MSG"

    monkeypatch.setattr(settings_routes, "test_vk", fake_test_vk)
    resp = await client.post("/settings/test-vk", follow_redirects=False)
    assert resp.status_code == 200
    assert "VK OK MSG" in resp.text


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, *a, **k):
        self._data = _FakeClient.next_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return _FakeResp(self._data)


async def test_vk_check_success(monkeypatch):
    _FakeClient.next_data = {"response": [{"id": 1, "name": "Моё сообщество"}]}
    monkeypatch.setattr(vk_check.httpx, "AsyncClient", _FakeClient)
    ok, msg = await vk_check.test_vk("sometoken")
    assert ok is True
    assert "Моё сообщество" in msg


async def test_vk_check_error(monkeypatch):
    _FakeClient.next_data = {"error": {"error_msg": "invalid token"}}
    monkeypatch.setattr(vk_check.httpx, "AsyncClient", _FakeClient)
    ok, msg = await vk_check.test_vk("sometoken")
    assert ok is False
    assert "invalid token" in msg
