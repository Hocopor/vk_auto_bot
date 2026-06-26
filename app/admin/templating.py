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
