"""Защитные механизмы админки: security-заголовки + rate-limit на /login.

- `SecurityHeadersMiddleware` — добавляет к каждому ответу набор заголовков,
  закрывающих типовые клиентские атаки (clickjacking, MIME-sniffing, утечка
  реферера), и Content-Security-Policy. Прячет идентификацию сервера.
- Rate-limit логина — простой in-memory счётчик неудачных попыток по IP
  (admin-web = один процесс, общего стейта не нужно). Защищает от брутфорса
  пароля при известном логине `admin` поверх HTTP.

IP клиента берём из ПОСЛЕДНЕГО значения `X-Forwarded-For` — его проставляет
наш Caddy из реального TCP-пира, в отличие от первых значений, которые может
подделать атакующий.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

# Content-Security-Policy: свой источник + Google Fonts (единственная внешняя
# зависимость шаблонов). 'unsafe-inline' для script/style — в шаблонах есть
# инлайн-обработчики (переключатель темы, клик по строке участника) и инлайн-
# стили в письмах форм; data: для превью загружаемых картинок (FileReader).
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "frame-src 'self'; "
    # 'self' (не 'none'): админка встраивает СВОЙ же эндпоинт чека в <iframe>
    # (превью PDF). Чужие сайты фреймить нас всё равно не могут.
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Проставляет защитные заголовки на каждый ответ админки."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        # SAMEORIGIN, не DENY: нужен для превью PDF-чека в <iframe> (тот же origin).
        # От clickjacking с чужих доменов всё равно защищает.
        headers["X-Frame-Options"] = "SAMEORIGIN"
        headers["Referrer-Policy"] = "same-origin"
        headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        headers["Content-Security-Policy"] = _CSP
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
        # Прячем софт/версию (не отдаём наводку атакующему).
        headers["Server"] = "web"
        return response


# ---- Rate-limit логина (in-memory, по IP) ----

#: окно учёта неудачных попыток (сек) и максимум попыток в окне.
LOGIN_WINDOW_SEC = 300
LOGIN_MAX_FAILS = 5

_failures: dict[str, list[float]] = {}


def client_ip(request: Request) -> str:
    """Реальный IP клиента (последний элемент X-Forwarded-For от нашего Caddy)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def _prune(ip: str, now: float) -> list[float]:
    fresh = [t for t in _failures.get(ip, []) if now - t < LOGIN_WINDOW_SEC]
    if fresh:
        _failures[ip] = fresh
    else:
        _failures.pop(ip, None)
    return fresh


def is_login_blocked(ip: str) -> bool:
    """True, если по IP накопилось >= LOGIN_MAX_FAILS неудач за окно."""
    return len(_prune(ip, time.time())) >= LOGIN_MAX_FAILS


def record_login_failure(ip: str) -> None:
    now = time.time()
    fresh = _prune(ip, now)
    fresh.append(now)
    _failures[ip] = fresh


def reset_login_failures(ip: str) -> None:
    """Сброс счётчика после успешного входа."""
    _failures.pop(ip, None)
