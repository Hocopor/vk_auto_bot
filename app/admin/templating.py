"""Единый Jinja2Templates для всей админки — общий фильтр localdt и подписи плейсхолдеров."""

from fastapi.templating import Jinja2Templates

from app.core import timeutil

templates = Jinja2Templates(directory="app/admin/templates")

templates.env.filters["localdt"] = timeutil.format_local_input

VAR_LABELS = {
    "name": "Имя участника",
    "numbers": "Номера билетов",
    "count": "Сколько билетов",
    "price": "Цена билета",
    "sheet_url": "Ссылка на список участников",
    "event_name": "Название розыгрыша",
}
templates.env.globals["VAR_LABELS"] = VAR_LABELS

_settings_cache: dict[str, str] = {}


def refresh_settings_cache(admin_title: str = "Админка", winners_tab_enabled: bool = True):
    _settings_cache["admin_title"] = admin_title
    _settings_cache["winners_tab_enabled"] = winners_tab_enabled


def _get_admin_title() -> str:
    return _settings_cache.get("admin_title", "Админка")


def _is_winners_enabled() -> bool:
    return _settings_cache.get("winners_tab_enabled", True)


templates.env.globals["get_admin_title"] = _get_admin_title
templates.env.globals["is_winners_enabled"] = _is_winners_enabled
