import getpass
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def main() -> None:
    p1 = getpass.getpass("Новый пароль администратора: ")
    p2 = getpass.getpass("Повторите пароль: ")
    if p1 != p2:
        print("Пароли не совпадают.")
        return
    if not p1:
        print("Пустой пароль недопустим.")
        return
    h = pwd_context.hash(p1)
    print("\nДобавьте в .env строку:\n")
    print(f"ADMIN_PASSWORD_HASH={h}")

if __name__ == "__main__":
    main()
