from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    vk_token: str = ""
    vk_group_id: int = 0

    @field_validator("vk_group_id", mode="before")
    @classmethod
    def _empty_vk_group_id_to_zero(cls, v):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return 0
        return v
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost/vk_auto_bot"
    google_sa_json: str = "./secrets/service_account.json"
    admin_login: str = "admin"
    admin_password_hash: str = ""
    session_secret: str = "change-me"
    secrets_key: str = ""  # Fernet-ключ для шифрования секретов в БД (scripts/gen_secrets_key.py)
    receipts_dir: str = "./data/receipts"
    qr_dir: str = "./data/qr"  # хранение загруженных QR-картинок мероприятий
    # Внешний адрес админ-сервера для публичных ссылок на таблицу участников,
    # которые бот шлёт в сообщениях. Например: http://185.228.72.118:8080
    public_base_url: str = ""
    worker_interval_sec: int = 5
    tesseract_cmd: str = ""  # путь к tesseract.exe, если не в PATH (опционально)
    display_timezone: str = "Europe/Moscow"  # таймзона для отображения и ввода дат в админке


settings = Settings()
