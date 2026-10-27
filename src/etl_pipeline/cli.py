"""Batch loader. Same load service as the API, with the file hash as the idempotency key."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from etl_pipeline.application.errors import IdempotencyConflict
from etl_pipeline.application.receipts import receipt_to_dict
from etl_pipeline.composition import build_runtime
from etl_pipeline.config import Settings
from etl_pipeline.domain.models import RawOrder, Rejection
from etl_pipeline.infrastructure.ingest.orders import read_csv, read_jsonl
from etl_pipeline.infrastructure.ingest.parsing import IngestError, IngestItem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etl-pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    load_parser = sub.add_parser("load", help="ingest a CSV or JSONL file of orders")
    load_parser.add_argument("path", type=Path)
    load_parser.add_argument("--format", choices=("csv", "jsonl"), default=None)
    load_parser.add_argument("--idempotency-key", default=None)
    load_parser.add_argument("--database-url", default=None)
    load_parser.add_argument("--max-orders", type=int, default=50_000)
    args = parser.parse_args(argv)
    try:
        return _load(args)
    except IngestError as exc:
        _error(str(exc), code="INGEST_ERROR")
        return 2
    except IdempotencyConflict as exc:
        _error(str(exc), code=exc.code)
        return 3
    except OSError as exc:
        _error(str(exc), code="IO_ERROR")
        return 2


def _load(args: argparse.Namespace) -> int:
    path: Path = args.path
    if not path.is_file():
        _error(f"file not found: {path}", code="IO_ERROR")
        return 2
    digest = _sha256(path)
    key = args.idempotency_key or f"file-{digest}"
    fmt = args.format or _guess_format(path)
    reader = read_jsonl if fmt == "jsonl" else read_csv
    items = reader(path, max_orders=args.max_orders)
    orders: list[RawOrder] = []
    rejections: list[Rejection] = []
    for item in items:
        _collect(item, orders, rejections)
    settings = _settings(args.database_url)
    runtime = build_runtime(settings)
    result = runtime.load_service().execute(
        orders,
        idempotency_key=key,
        request_hash=digest,
        extra_rejections=rejections,
    )
    json.dump(receipt_to_dict(result.receipt), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _collect(item: IngestItem, orders: list[RawOrder], rejections: list[Rejection]) -> None:
    if item.order is not None:
        orders.append(item.order)
    if item.rejection is not None:
        rejections.append(item.rejection)


def _settings(database_url: str | None) -> Settings:
    if database_url:
        return Settings(database_url=database_url, log_level="WARNING", db_startup_retries=0)
    return Settings()


def _guess_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return "jsonl"
    return "csv"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error(message: str, *, code: str) -> None:
    json.dump({"code": code, "message": message}, sys.stderr)
    sys.stderr.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
