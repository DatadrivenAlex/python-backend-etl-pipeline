"""CSV and JSONL order readers.

Rows are grouped in memory by natural key. That is O(orders) RAM. A multi-gigabyte
extract should be split or pre-aggregated before it reaches this process; `max_orders`
fails closed instead of growing without a bound.
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from etl_pipeline.domain.models import Party, RawOrder, RawOrderLine, Rejection
from etl_pipeline.domain.time import ensure_utc
from etl_pipeline.infrastructure.ingest.parsing import (
    IngestError,
    IngestItem,
    RowParseError,
    empty_to_none,
    parse_timestamp,
    require_columns,
)

REQUIRED_COLUMNS = (
    "source_system",
    "external_id",
    "ordered_at",
    "currency",
    "seller_id",
    "seller_name",
    "seller_country",
    "seller_vat_id",
    "buyer_id",
    "buyer_name",
    "buyer_country",
    "buyer_vat_id",
    "sku",
    "description",
    "quantity",
    "unit_price",
    "vat_category",
)

_HEADER_FIELDS = (
    "ordered_at",
    "currency",
    "seller_id",
    "seller_name",
    "seller_country",
    "seller_vat_id",
    "buyer_id",
    "buyer_name",
    "buyer_country",
    "buyer_vat_id",
)


def read_csv(path: Path, *, max_orders: int = 50_000) -> list[IngestItem]:
    records = _records_from_csv(path)
    return items_from_row_dicts(records, max_orders=max_orders)


def read_csv_with_pandas(path: Path, *, max_orders: int = 50_000) -> list[IngestItem]:
    """Analyst path. The frame is materialized; prefer `read_csv` for throughput."""
    import pandas as pd

    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    require_columns(list(frame.columns), REQUIRED_COLUMNS)
    records = []
    for record in frame.to_dict(orient="records"):
        records.append({str(key): "" if value is None else str(value).strip() for key, value in record.items()})
    return items_from_row_dicts(records, max_orders=max_orders)


def read_jsonl(path: Path, *, max_orders: int = 50_000) -> list[IngestItem]:
    items: list[IngestItem] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            if len(items) >= max_orders:
                raise IngestError(f"file exceeds {max_orders} orders")
            items.append(_jsonl_line(line_no, raw))
    return items


def items_from_row_dicts(
    records: list[dict[str, str]],
    *,
    max_orders: int,
) -> list[IngestItem]:
    groups: dict[tuple[str, str], list[tuple[int, dict[str, str]]]] = {}
    positions: dict[tuple[str, str], int] = {}
    items: list[IngestItem | None] = []
    for index, record in enumerate(records, start=2):
        source = record.get("source_system", "").strip().lower()
        external = record.get("external_id", "").strip()
        if not source or not external:
            items.append(
                IngestItem(
                    rejection=Rejection(
                        source_system=source,
                        external_id=external or f"line-{index}",
                        code="PARSE_ERROR",
                        message=f"line {index}: source_system and external_id are required",
                    )
                )
            )
            continue
        key = (source, external)
        if key not in positions:
            if len(groups) >= max_orders:
                raise IngestError(f"file exceeds {max_orders} orders")
            positions[key] = len(items)
            items.append(None)
            groups[key] = []
        groups[key].append((index, record))
    for key, position in positions.items():
        items[position] = _build_group(key, groups[key])
    return [item for item in items if item is not None]


def _records_from_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise IngestError("CSV is empty") from exc
        columns = [cell.strip().lower() for cell in header]
        require_columns(columns, REQUIRED_COLUMNS)
        records: list[dict[str, str]] = []
        width = len(columns)
        for raw in reader:
            if not any(cell.strip() for cell in raw):
                continue
            padded = list(raw) + [""] * (width - len(raw))
            records.append({columns[i]: padded[i].strip() for i in range(width)})
        return records


def _build_group(
    key: tuple[str, str],
    rows: list[tuple[int, dict[str, str]]],
) -> IngestItem:
    source, external = key
    signatures = {_signature(row) for _, row in rows}
    if len(signatures) != 1:
        return IngestItem(
            rejection=Rejection(
                source_system=source,
                external_id=external,
                code="INCONSISTENT_ORDER_HEADER",
                message="seller, buyer, currency, or ordered_at differs between lines",
            )
        )
    first_line, first = rows[0]
    try:
        lines = tuple(_parse_line(line_no, row) for line_no, row in rows)
        order = RawOrder(
            source_system=source,
            external_id=external,
            ordered_at=parse_timestamp(first["ordered_at"], line_no=first_line),
            currency=first["currency"].strip().upper(),
            seller=Party(
                party_id=first["seller_id"].strip(),
                name=first["seller_name"].strip(),
                country=first["seller_country"].strip(),
                vat_id=empty_to_none(first["seller_vat_id"]),
            ),
            buyer=Party(
                party_id=first["buyer_id"].strip(),
                name=first["buyer_name"].strip(),
                country=first["buyer_country"].strip(),
                vat_id=empty_to_none(first["buyer_vat_id"]),
            ),
            lines=lines,
        )
    except RowParseError as exc:
        return IngestItem(
            rejection=Rejection(
                source_system=source,
                external_id=external,
                code="PARSE_ERROR",
                message=str(exc),
            )
        )
    return IngestItem(order=order)


def _signature(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row.get(field, "").strip() for field in _HEADER_FIELDS)


def _parse_line(line_no: int, row: dict[str, str]) -> RawOrderLine:
    try:
        quantity = Decimal(row.get("quantity", "").strip())
        unit_price = Decimal(row.get("unit_price", "").strip())
    except InvalidOperation as exc:
        raise RowParseError(f"line {line_no}: quantity or unit_price is not a decimal") from exc
    sku = row.get("sku", "").strip()
    description = row.get("description", "").strip()
    category = row.get("vat_category", "").strip()
    if not sku or not description or not category:
        raise RowParseError(f"line {line_no}: sku, description, and vat_category are required")
    return RawOrderLine(
        sku=sku,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        vat_category=category,
    )


def _jsonl_line(line_no: int, raw: str) -> IngestItem:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return IngestItem(
            rejection=Rejection(
                source_system="",
                external_id=f"line-{line_no}",
                code="PARSE_ERROR",
                message=f"line {line_no}: invalid JSON ({exc.msg})",
            )
        )
    if not isinstance(payload, dict):
        return _json_rejection(line_no, "", "JSON value must be an object")
    source = str(payload.get("source_system", "")).strip().lower()
    external = str(payload.get("external_id", "")).strip()
    if not source or not external:
        return _json_rejection(line_no, external, "source_system and external_id are required")
    try:
        seller = _party(payload.get("seller"), line_no=line_no, role="seller")
        buyer = _party(payload.get("buyer"), line_no=line_no, role="buyer")
        raw_lines = payload.get("lines")
        if not isinstance(raw_lines, list) or not raw_lines:
            raise RowParseError(f"line {line_no}: lines must be a non-empty array")
        lines = tuple(_json_line(line_no, item, index) for index, item in enumerate(raw_lines, start=1))
        ordered_at = parse_timestamp(str(payload.get("ordered_at", "")), line_no=line_no)
        currency = str(payload.get("currency", "")).strip().upper()
        order = RawOrder(
            source_system=source,
            external_id=external,
            ordered_at=ensure_utc(ordered_at),
            currency=currency,
            seller=seller,
            buyer=buyer,
            lines=lines,
        )
    except RowParseError as exc:
        return IngestItem(
            rejection=Rejection(
                source_system=source,
                external_id=external,
                code="PARSE_ERROR",
                message=str(exc),
            )
        )
    return IngestItem(order=order)


def _party(value: object, *, line_no: int, role: str) -> Party:
    if not isinstance(value, dict):
        raise RowParseError(f"line {line_no}: {role} must be an object")
    party_id = str(value.get("party_id", "")).strip()
    name = str(value.get("name", "")).strip()
    country = str(value.get("country", "")).strip()
    if not party_id or not name or not country:
        raise RowParseError(f"line {line_no}: {role} party_id, name, and country are required")
    vat_raw = value.get("vat_id")
    vat_id = None if vat_raw is None or str(vat_raw).strip() == "" else str(vat_raw).strip()
    return Party(party_id=party_id, name=name, country=country, vat_id=vat_id)


def _json_line(line_no: int, value: object, index: int) -> RawOrderLine:
    if not isinstance(value, dict):
        raise RowParseError(f"line {line_no}: line item {index} must be an object")
    quantity = _json_decimal(value.get("quantity"), f"line {line_no} quantity")
    unit_price = _json_decimal(value.get("unit_price"), f"line {line_no} unit_price")
    sku = str(value.get("sku", "")).strip()
    description = str(value.get("description", "")).strip()
    category = str(value.get("vat_category", "")).strip()
    if not sku or not description or not category:
        raise RowParseError(
            f"line {line_no}: line item {index} is missing sku, description, or vat_category"
        )
    return RawOrderLine(
        sku=sku,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        vat_category=category,
    )


def _json_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise RowParseError(f"{field} must be a string or integer, not a JSON number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation as exc:
            raise RowParseError(f"{field} is not a decimal") from exc
    raise RowParseError(f"{field} is missing")


def _json_rejection(line_no: int, external: str, message: str) -> IngestItem:
    return IngestItem(
        rejection=Rejection(
            source_system="",
            external_id=external or f"line-{line_no}",
            code="PARSE_ERROR",
            message=f"line {line_no}: {message}",
        )
    )

