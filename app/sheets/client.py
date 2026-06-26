"""Lazy gspread client authorized via Google service account."""

import gspread
from google.oauth2.service_account import Credentials

from app.core.config import settings

_client: gspread.Client | None = None


def get_client() -> gspread.Client:
    """Return cached gspread Client, authorizing on first call."""
    global _client
    if _client is None:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            settings.google_sa_json, scopes=scopes
        )
        _client = gspread.authorize(creds)
    return _client


def reset_client() -> None:
    """Reset cached client (for testing)."""
    global _client
    _client = None
