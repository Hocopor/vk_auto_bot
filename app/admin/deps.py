from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Request
from fastapi.responses import RedirectResponse
from pydantic import BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker


def _empty_to_none(value):
    """Пустая строка из формы/дропдауна (`?event_id=`) → None, иначе значение как есть.

    HTML-`<select>` всегда отправляет выбранный value; пункт «Все мероприятия» имеет
    value="" → без этой нормализации int|None-параметр падает с 422 int_parsing.
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    return value


# Опциональный int-параметр запроса, терпимый к пустой строке ("" → None).
OptionalInt = Annotated[int | None, BeforeValidator(_empty_to_none)]


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
