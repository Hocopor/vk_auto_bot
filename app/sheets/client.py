import gspread
from google.oauth2.service_account import Credentials

from app.core.config import settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None


def get_client() -> gspread.Client:
    """Ленивая инициализация gspread-клиента по service account. Кэшируется на процесс.

    Бросает исключение, если JSON недоступен/некорректен — вызывающий код в sync.py это ловит.
    """
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(settings.google_sa_json, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client
