"""Coerce driver values into Decimal and UTC datetimes. Floats are refused."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from etl_pipeline.domain.time import ensure_utc


def as_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("refusing to coerce a float read from the database")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError(f"unsupported decimal value {value!r}")
    return Decimal(str(value))


def as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        return ensure_utc(datetime.fromisoformat(text))
    raise TypeError(f"unsupported datetime value {value!r}")
