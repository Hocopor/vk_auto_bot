"""Tests for Google Sheets sync logic (no real API calls)."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from app.sheets.sync import extract_sheet_id, reader_url, HEADER, PAID_MARK


def test_extract_sheet_id_full_url():
    url = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit?usp=sharing"
    assert extract_sheet_id(url) == "1AbCdEfGhIjKlMnOpQrStUvWxYz"


def test_extract_sheet_id_no_edit():
    url = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz"
    assert extract_sheet_id(url) == "1AbCdEfGhIjKlMnOpQrStUvWxYz"


def test_extract_sheet_id_short_id():
    url = "https://docs.google.com/spreadsheets/d/abc123/"
    assert extract_sheet_id(url) == "abc123"


def test_extract_sheet_id_invalid():
    with pytest.raises(ValueError, match="Cannot extract"):
        extract_sheet_id("https://example.com/not-a-sheet")


def test_extract_sheet_id_empty():
    with pytest.raises(ValueError, match="Cannot extract"):
        extract_sheet_id("")


def test_reader_url_from_edit_url():
    url = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit?usp=sharing"
    assert reader_url(url) == "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/preview"


def test_reader_url_from_bare_url():
    url = "https://docs.google.com/spreadsheets/d/abc123"
    assert reader_url(url) == "https://docs.google.com/spreadsheets/d/abc123/preview"


@pytest.mark.asyncio
async def test_sync_creates_header_on_empty_sheet():
    from app.sheets.sync import sync_event_to_sheet

    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = []

    mock_sheet = MagicMock()
    mock_sheet.sheet1 = mock_ws

    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet

    mock_session = MagicMock()

    with patch("app.sheets.sync.collect_approved_records", return_value=[(1, "Иван"), (2, "Мария")]):
        with patch("app.sheets.client.get_client", return_value=mock_gc):
            await sync_event_to_sheet(
                mock_session,
                event_id=42,
                google_sheet_url="https://docs.google.com/spreadsheets/d/test123/edit",
            )

    mock_ws.clear.assert_called_once()
    mock_ws.append_row.assert_called_once_with(HEADER, value_input_option="RAW")
    mock_ws.append_rows.assert_called_once_with(
        [["1", "Иван", PAID_MARK], ["2", "Мария", PAID_MARK]],
        value_input_option="RAW",
    )


@pytest.mark.asyncio
async def test_sync_corrects_header():
    from app.sheets.sync import sync_event_to_sheet

    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [["Wrong", "Header"]]

    mock_sheet = MagicMock()
    mock_sheet.sheet1 = mock_ws

    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet

    mock_session = MagicMock()

    with patch("app.sheets.sync.collect_approved_records", return_value=[(5, "Тест")]):
        with patch("app.sheets.client.get_client", return_value=mock_gc):
            await sync_event_to_sheet(
                mock_session,
                event_id=1,
                google_sheet_url="https://docs.google.com/spreadsheets/d/abc/edit",
            )

    mock_ws.clear.assert_called_once()
    mock_ws.append_row.assert_called_once_with(HEADER, value_input_option="RAW")


@pytest.mark.asyncio
async def test_sync_deletes_extra_rows():
    from app.sheets.sync import sync_event_to_sheet

    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        HEADER,
        ["1", "Old", PAID_MARK],
        ["2", "Gone", PAID_MARK],
        ["3", "Also gone", PAID_MARK],
    ]

    mock_sheet = MagicMock()
    mock_sheet.sheet1 = mock_ws

    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet

    mock_session = MagicMock()

    with patch("app.sheets.sync.collect_approved_records", return_value=[(1, "Новый")]):
        with patch("app.sheets.client.get_client", return_value=mock_gc):
            await sync_event_to_sheet(
                mock_session,
                event_id=99,
                google_sheet_url="https://docs.google.com/spreadsheets/d/xyz/edit",
            )

    mock_ws.delete_rows.assert_called_once_with(3, 4)
    mock_ws.update.assert_called_once_with(
        "A2:C2", [["1", "Новый", PAID_MARK]], value_input_option="RAW"
    )


@pytest.mark.asyncio
async def test_sync_no_records_clears_data():
    from app.sheets.sync import sync_event_to_sheet

    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [HEADER, ["1", "Old", PAID_MARK]]

    mock_sheet = MagicMock()
    mock_sheet.sheet1 = mock_ws

    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet

    mock_session = MagicMock()

    with patch("app.sheets.sync.collect_approved_records", return_value=[]):
        with patch("app.sheets.client.get_client", return_value=mock_gc):
            await sync_event_to_sheet(
                mock_session,
                event_id=1,
                google_sheet_url="https://docs.google.com/spreadsheets/d/abc/edit",
            )

    mock_ws.delete_rows.assert_called_once_with(2, 2)


@pytest.mark.asyncio
async def test_sync_raise_on_error_true_propagates_exception():
    from app.sheets.sync import sync_event_to_sheet

    mock_session = MagicMock()

    with patch("app.sheets.sync.collect_approved_records", return_value=[]):
        with patch("app.sheets.client.get_client", side_effect=RuntimeError("auth failed")):
            with pytest.raises(RuntimeError, match="auth failed"):
                await sync_event_to_sheet(
                    mock_session,
                    event_id=1,
                    google_sheet_url="https://docs.google.com/spreadsheets/d/abc/edit",
                    raise_on_error=True,
                )


@pytest.mark.asyncio
async def test_sync_raise_on_error_false_swallows_exception(caplog):
    from app.sheets.sync import sync_event_to_sheet

    mock_session = MagicMock()

    with patch("app.sheets.sync.collect_approved_records", return_value=[]):
        with patch("app.sheets.client.get_client", side_effect=RuntimeError("auth failed")):
            with caplog.at_level(logging.ERROR):
                # default raise_on_error=False — должно проглотить, не упасть
                await sync_event_to_sheet(
                    mock_session,
                    event_id=1,
                    google_sheet_url="https://docs.google.com/spreadsheets/d/abc/edit",
                )

    assert any("Failed to sync event" in record.message for record in caplog.records)
