from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    vk_token: str = ""
    vk_group_id: int = 0
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost/vk_auto_bot"
    google_sa_json: str = "./secrets/service_account.json"
    admin_login: str = "admin"
    admin_password_hash: str = ""
    session_secret: str = "change-me"
    receipts_dir: str = "./data/receipts"
    qr_dir: str = "./data/qr"  # хранение загруженных QR-картинок мероприятий
    worker_interval_sec: int = 5
    tesseract_cmd: str = ""  # путь к tesseract.exe, если не в PATH (опционально)


settings = Settings()
