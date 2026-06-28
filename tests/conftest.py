import pytest


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """Сбрасываем in-memory счётчик неудачных логинов между тестами.

    Счётчик `app.admin.security._failures` — модульный глобал, иначе попытки
    из одного теста протекали бы в другой (ложный 429).
    """
    from app.admin import security

    security._failures.clear()
    yield
    security._failures.clear()
