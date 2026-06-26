"""Tests for dark theme functionality."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.deps import get_session, require_login
from app.admin.main import app
from app.core import models  # noqa: F401
from app.core.db import Base


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
        async with maker() as session:
            yield session

    async def _require_login_override():
        return "admin"

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[require_login] = _require_login_override

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_login, None)


async def test_base_html_has_theme_toggle(client):
    """base.html should contain theme toggle button."""
    resp = await client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "theme-toggle" in html


async def test_base_html_has_data_theme_support(client):
    """base.html should have data-theme attribute support via admin.js."""
    resp = await client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "admin.js" in html


async def test_base_html_has_admin_title(client):
    """Page title should use get_admin_title() (defaults to Админка)."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Админка" in resp.text


async def test_admin_js_contains_theme_logic():
    """admin.js should have theme toggle logic."""
    import pathlib

    js_path = pathlib.Path("app/admin/static/admin.js")
    content = js_path.read_text(encoding="utf-8")
    assert "theme-toggle" in content
    assert "localStorage" in content
    assert "data-theme" in content
    assert "getTheme" in content or "setTheme" in content


async def test_settings_page_has_winners_toggle(client):
    """Settings page should have winners_tab_enabled checkbox."""
    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "winners_tab_enabled" in resp.text


async def test_settings_page_has_admin_title_field(client):
    """Settings page should have admin_title input."""
    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "admin_title" in resp.text
