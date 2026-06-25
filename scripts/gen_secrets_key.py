"""Генерация Fernet-ключа для SECRETS_KEY в .env (шифрование секретов в БД)."""
from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(Fernet.generate_key().decode())
