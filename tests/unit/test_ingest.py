from pathlib import Path

import pytest

from etl_pipeline.infrastructure.ingest.orders import read_csv, read_csv_with_pandas, read_jsonl
from etl_pipeline.infrastructure.ingest.parsing import IngestError
from tests.conftest import FIXTURES


def test_csv_groups_lines_and_keeps_bad_orders() -> None:
    items = read_csv(FIXTURES / "orders_sample.csv")
    orders = {item.order.external_id: item.order for item in items if item.order is not None}
    rejections = [item.rejection for item in items if item.rejection is not None]
    assert set(orders) == {"INV-100", "INV-200", "INV-300", "INV-BAD"}
    assert len(orders["INV-100"].lines) == 2
    assert orders["INV-100"].buyer.name == "Müller AG"
    assert orders["INV-300"].buyer.vat_id is None
    assert orders["INV-BAD"].lines[0].quantity < 0
    assert rejections == []


def test_inconsistent_header_rejects_the_whole_order(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    path.write_text(
        "source_system,external_id,ordered_at,currency,seller_id,seller_name,seller_country,"
        "seller_vat_id,buyer_id,buyer_name,buyer_country,buyer_vat_id,sku,description,quantity,"
        "unit_price,vat_category\n"
        "erp-de,INV-1,2026-01-15T08:30:00+00:00,EUR,SELL-1,Nordlicht GmbH,DE,DE123456789,"
        "BUY-1,Müller AG,DE,DE987654321,SKU-1,One,1,10,standard\n"
        "erp-de,INV-1,2026-01-15T08:30:00+00:00,EUR,SELL-1,Nordlicht GmbH,DE,DE123456789,"
        "BUY-9,Other AG,DE,DE987654321,SKU-2,Two,1,10,standard\n",
        encoding="utf-8",
    )
    items = read_csv(path)
    assert items[0].order is None
    assert items[0].rejection is not None
    assert items[0].rejection.code == "INCONSISTENT_ORDER_HEADER"


def test_missing_column_is_a_file_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("source_system,external_id\n", encoding="utf-8")
    with pytest.raises(IngestError, match="missing columns"):
        read_csv(path)


def test_max_orders_fails_closed(tmp_path: Path) -> None:
    header = (
        "source_system,external_id,ordered_at,currency,seller_id,seller_name,seller_country,"
        "seller_vat_id,buyer_id,buyer_name,buyer_country,buyer_vat_id,sku,description,quantity,"
        "unit_price,vat_category\n"
    )
    rows = []
    for index in range(2):
        rows.append(
            "erp-de,INV-"
            f"{index},2026-01-15T08:30:00+00:00,EUR,SELL-1,Nordlicht GmbH,DE,DE123456789,"
            "BUY-1,Müller AG,DE,DE987654321,SKU-1,One,1,10,standard"
        )
    path = tmp_path / "two.csv"
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(IngestError, match="exceeds"):
        read_csv(path, max_orders=1)


def test_jsonl_rejects_float_prices() -> None:
    items = read_jsonl(FIXTURES / "orders_sample.jsonl")
    assert items[0].order is not None
    assert items[0].order.ordered_at.tzinfo is not None
    assert items[1].order is None
    assert items[1].rejection is not None
    assert items[1].rejection.code == "PARSE_ERROR"
    assert "JSON number" in items[1].rejection.message


def test_pandas_reader_matches_the_stdlib_reader() -> None:
    pytest.importorskip("pandas")
    stdlib = read_csv(FIXTURES / "orders_sample.csv")
    pandas_items = read_csv_with_pandas(FIXTURES / "orders_sample.csv")
    assert [item.order.external_id if item.order else None for item in pandas_items] == [
        item.order.external_id if item.order else None for item in stdlib
    ]
    assert pandas_items[0].order is not None and stdlib[0].order is not None
    assert pandas_items[0].order.lines[0].unit_price == stdlib[0].order.lines[0].unit_price
