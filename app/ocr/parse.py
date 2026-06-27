import re
from datetime import date
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


_MONTHS_RU = {
    "января": 1, "январь": 1, "февраля": 2, "февраль": 2, "марта": 3, "март": 3,
    "апреля": 4, "апрель": 4, "мая": 5, "май": 5, "июня": 6, "июнь": 6,
    "июля": 7, "июль": 7, "августа": 8, "август": 8, "сентября": 9, "сентябрь": 9,
    "октября": 10, "октябрь": 10, "ноября": 11, "ноябрь": 11, "декабря": 12, "декабрь": 12,
}

# dd.mm.yyyy / dd.mm.yy / dd-mm-yyyy / dd/mm/yyyy (день первым — формат РФ)
_DATE_DMY_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b")
# ISO: yyyy-mm-dd
_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
# dd <месяц словом> yyyy
_DATE_RU_RE = re.compile(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b", re.IGNORECASE)

_SIGNATURE_RE = re.compile(
    r"(?:номер операци\w*|идентификатор операци\w*|номер документа|"
    r"номер квитанци\w*|номер чека|операци\w*|квитанци\w*|чек|документ)"
    r"\s*[:№#\-]?\s*([A-Za-zА-Яа-я0-9\-]{5,40})",
    re.IGNORECASE,
)


def _safe_date(year: int, month: int, day: int) -> date | None:
    if year < 100:
        year += 2000
    if not (1 <= month <= 12 and 1 <= day <= 31 and 2000 <= year <= 2100):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_receipt_date(text: str) -> date | None:
    """Извлечь дату чека из распознанного текста. Возвращает первую валидную дату
    в порядке появления в тексте, либо None."""
    if not text:
        return None
    candidates: list[tuple[int, date]] = []
    for m in _DATE_ISO_RE.finditer(text):
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            candidates.append((m.start(), d))
    for m in _DATE_DMY_RE.finditer(text):
        d = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d:
            candidates.append((m.start(), d))
    for m in _DATE_RU_RE.finditer(text):
        month = _MONTHS_RU.get(m.group(2).lower())
        if month:
            d = _safe_date(int(m.group(3)), month, int(m.group(1)))
            if d:
                candidates.append((m.start(), d))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def parse_receipt_signature(text: str) -> str | None:
    """Извлечь реквизит-подпись чека (номер операции/документа) для глобального
    дедупа. Best-effort: None, если не найдено. Нормализуется в верхний регистр."""
    if not text:
        return None
    m = _SIGNATURE_RE.search(text)
    if not m:
        return None
    token = m.group(1).strip().upper()
    # отсекаем чисто словесные ложные срабатывания: должна быть хотя бы одна цифра
    if not any(ch.isdigit() for ch in token):
        return None
    return token


def parse_receipt(raw_text: str, expected_recipient: str | None) -> dict:
    """Высокоуровневая обёртка: сумма, получатель, дата, реквизит-подпись."""
    return {
        "amount": parse_amount(raw_text),
        "recipient_found": find_recipient(raw_text, expected_recipient),
        "receipt_date": parse_receipt_date(raw_text),
        "signature": parse_receipt_signature(raw_text),
        "raw_text": raw_text,
    }
