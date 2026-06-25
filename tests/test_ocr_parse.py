from decimal import Decimal

from app.ocr.parse import (
    find_recipient,
    normalize_recipient,
    parse_amount,
    parse_receipt,
)


def test_parse_amount_itogo_with_comma():
    assert parse_amount("Итого: 1 000,00 ₽") == Decimal("1000.00")


def test_parse_amount_summa_perevoda():
    assert parse_amount("Сумма перевода\n2 500 ₽") == Decimal("2500")


def test_parse_amount_rubl_short_form():
    assert parse_amount("Перевёл 500р получателю") == Decimal("500")


def test_parse_amount_rub_latin():
    assert parse_amount("1000.00 RUB") == Decimal("1000.00")


def test_parse_amount_takes_max_priority_candidate():
    # Комиссия 0 ₽ отброшена как < 1, итого 750.00 - максимум приоритетных
    assert parse_amount(
        "Чек об оплате\nКомиссия 0 ₽\nИтого 750,00 ₽"
    ) == Decimal("750.00")


def test_parse_amount_none_when_no_money():
    assert parse_amount("просто текст без денег") is None


def test_parse_amount_k_oplate():
    assert parse_amount("К оплате 3 300,50 ₽") == Decimal("3300.50")


def test_parse_amount_ignores_plain_numbers_without_currency():
    # Числа без ключевого слова и без валюты не считаются суммой
    assert parse_amount("Заказ номер 12345, дата 2024") is None


def test_find_recipient_quotes_and_ownership_form():
    assert find_recipient('Получатель ООО "Ромашка"', "Ромашка") is True


def test_find_recipient_expected_has_ownership_form():
    assert find_recipient("Получатель: Ромашка", "ООО Ромашка") is True


def test_find_recipient_mismatch():
    assert find_recipient("Иванов Иван", "Ромашка") is False


def test_find_recipient_empty_expected():
    assert find_recipient("что угодно", None) is False
    assert find_recipient("что угодно", "") is False


def test_normalize_recipient_basic():
    assert normalize_recipient('ООО «Ромашка»') == "ромашка"


def test_parse_receipt_combined():
    result = parse_receipt("Итого 1 000 ₽\nПолучатель ООО Ромашка", "Ромашка")
    assert result["amount"] == Decimal("1000")
    assert result["recipient_found"] is True
    assert result["raw_text"] == "Итого 1 000 ₽\nПолучатель ООО Ромашка"


def test_parse_receipt_no_recipient_match():
    result = parse_receipt("Итого 1 000 ₽\nПолучатель Иванов И.И.", "Ромашка")
    assert result["amount"] == Decimal("1000")
    assert result["recipient_found"] is False
