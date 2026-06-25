from collections.abc import AsyncGenerator

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker


class NotAuthenticated(Exception):
    """Поднимается, когда нет активной сессии — перехватывается обработчиком и редиректит на /login."""


def require_login(request: Request) -> str:
    """FastAPI-зависимость: вернуть логин из сессии или поднять NotAuthenticated."""
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
