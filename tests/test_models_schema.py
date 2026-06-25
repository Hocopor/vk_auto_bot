import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base


@pytest.mark.asyncio
async def test_schema_creates_all_tables_on_sqlite():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            def _inspect(sync_conn):
                from sqlalchemy import inspect

                inspector = inspect(sync_conn)
                tables = set(inspector.get_table_names())
                expected = {
                    "events",
                    "participants",
                    "purchases",
                    "poster_numbers",
                    "bot_dialog_state",
                }
                assert expected.issubset(tables), tables

                # уникальное ограничение/индекс (event_id, number) на poster_numbers
                uniques = inspector.get_unique_constraints("poster_numbers")
                indexes = inspector.get_indexes("poster_numbers")
                combos = [set(u["column_names"]) for u in uniques]
                combos += [set(i["column_names"]) for i in indexes if i.get("unique")]
                assert {"event_id", "number"} in combos, (uniques, indexes)

                return len(expected.intersection(tables))

            n = await conn.run_sync(_inspect)
            assert n == 5
            print(f"schema OK, tables={n}")
    finally:
        await engine.dispose()
