from cryptography.fernet import Fernet

from app.core.config import settings


def _fernet() -> Fernet:
    if not settings.secrets_key:
        raise RuntimeError(
            "SECRETS_KEY не задан в .env — сгенерируй: python scripts/gen_secrets_key.py"
        )
    return Fernet(settings.secrets_key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
