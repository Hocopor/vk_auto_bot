from datetime import timezone

from app.core import timeutil


def test_parse_local_datetime_msk_to_utc():
    # 12:00 по Europe/Moscow (UTC+3) -> 09:00 UTC
    dt = timeutil.parse_local_datetime("2026-06-26T12:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.astimezone(timezone.utc).hour == 9
    assert dt.astimezone(timezone.utc).minute == 0
    assert dt.astimezone(timezone.utc).year == 2026
    assert dt.astimezone(timezone.utc).month == 6
    assert dt.astimezone(timezone.utc).day == 26


def test_parse_local_datetime_empty():
    assert timeutil.parse_local_datetime("") is None
    assert timeutil.parse_local_datetime(None) is None
    assert timeutil.parse_local_datetime("   ") is None


def test_format_local_input_roundtrip():
    dt = timeutil.parse_local_datetime("2026-06-26T12:00")
    assert timeutil.format_local_input(dt) == "2026-06-26T12:00"


def test_format_local_input_none():
    assert timeutil.format_local_input(None) == ""


def test_to_local_naive_treated_as_utc():
    from datetime import datetime

    naive = datetime(2026, 6, 26, 9, 0, 0)
    local = timeutil.to_local(naive)
    assert local is not None
    assert local.hour == 12
