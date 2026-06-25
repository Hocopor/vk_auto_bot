import re
from decimal import Decimal, InvalidOperation

# Денежные значения: 1 000,00 / 1000.00 / 1 000 ₽ / 500р и т.п.
# группа числа допускает пробелы (вкл. неразрывный) как разделители тысяч.

_NBSP = " "

_KEYWORDS_PATTERN = re.compile(
    r"(?:итого|сумма[^\n]{0,20}?|перевод|оплата|к оплате|всего)"
    r"\D{0,15}?(\d[\d\s" + _NBSP + r"]*(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)

_CURRENCY_PATTERN = re.compile(
    r"(\d[\d\s" + _NBSP + r"]*(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|лей|ля)?|р\.?\b|rub\b)",
    re.IGNORECASE,
)

_OWNERSHIP_FORMS = {"ооо", "оао", "зао", "пао", "ип", "ао", "нко", "тоо"}

_QUOTES_PATTERN = re.compile(r"[«»\"'`]")
_WHITESPACE_PATTERN = re.compile(r"[\s" + _NBSP + r"]+")


def _to_decimal(raw: str) -> Decimal | None:
    """Преобразовать строку числа вида «1 000,00» / «1000.00» / «500» в Decimal."""
    if not raw:
        return None
    s = raw.replace(" ", "").replace(_NBSP, "")
    s = s.replace(",", ".")
    # если точек несколько (разделители тысяч точками) — оставить последнюю как десятичную
    if s.count(".") > 1:
        parts = s.split(".")
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def parse_amount(text: str) -> Decimal | None:
    """Извлечь сумму платежа из распознанного текста чека."""
    priority_candidates: list[Decimal] = []

    for match in _KEYWORDS_PATTERN.finditer(text):
        value = _to_decimal(match.group(1))
        if value is not None and value >= 1:
            priority_candidates.append(value)

    for match in _CURRENCY_PATTERN.finditer(text):
        value = _to_decimal(match.group(1))
        if value is not None and value >= 1:
            priority_candidates.append(value)

    if priority_candidates:
        return max(priority_candidates)

    return None


def normalize_recipient(s: str) -> str:
    """Нормализовать строку получателя: lower, без кавычек/форм собственности, схлопнутые пробелы."""
    if not s:
        return ""
    text = s.lower()
    text = _QUOTES_PATTERN.sub("", text)

    tokens = _WHITESPACE_PATTERN.split(text)
    tokens = [t for t in tokens if t and t not in _OWNERSHIP_FORMS]
    return " ".join(tokens).strip()


def find_recipient(text: str, expected: str | None) -> bool:
    """Проверить, совпал ли ожидаемый получатель с текстом чека."""
    if not expected:
        return False

    norm_text = normalize_recipient(text)
    norm_exp = normalize_recipient(expected)

    if not norm_exp:
        return False

    if norm_exp in norm_text:
        return True

    significant_tokens = [t for t in norm_exp.split(" ") if len(t) >= 3]
    if significant_tokens and all(t in norm_text for t in significant_tokens):
        return True

    return False


def parse_receipt(raw_text: str, expected_recipient: str | None) -> dict:
    """Высокоуровневая обёртка: извлечь сумму и проверить получателя."""
    amount = parse_amount(raw_text)
    recipient_found = find_recipient(raw_text, expected_recipient)
    return {
        "amount": amount,
        "recipient_found": recipient_found,
        "raw_text": raw_text,
    }
