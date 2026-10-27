"""Shared ingest errors and timestamp parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from etl_pipeline.domain.models import RawOrder, Rejection
from etl_pipeline.domain.time import ensure_utc


class IngestError(Exception):
    """The file cannot be read as a batch. This is not a single-row rejection."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class IngestItem:
    order: RawOrder | None = None
    rejection: Rejection | None = None


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


class RowParseError(Exception):
    pass


def require_columns(present: list[str], required: tuple[str, ...]) -> None:
    missing = [column for column in required if column not in present]
    if missing:
        raise IngestError("missing columns: " + ", ".join(missing))


def parse_timestamp(value: str, *, line_no: int) -> datetime:
    text = value.strip()
    if not text:
        raise RowParseError(f"line {line_no}: ordered_at is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RowParseError(f"line {line_no}: ordered_at is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RowParseError(f"line {line_no}: ordered_at must include a timezone offset")
    return ensure_utc(parsed)
