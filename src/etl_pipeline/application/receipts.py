"""Load results. JSON in the idempotency table is this shape and nothing else."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from etl_pipeline.domain.models import Rejection

# The rejection table keeps every row. The API body and the stored receipt embed a prefix.
MAX_EMBEDDED_REJECTIONS = 100


@dataclass(frozen=True, slots=True)
class LoadReceipt:
    load_id: str
    idempotency_key: str
    accepted: int
    rejected: int
    inserted: int
    updated: int
    unchanged: int
    duration_ms: int
    rejections: tuple[Rejection, ...]


@dataclass(frozen=True, slots=True)
class StoredLoad:
    idempotency_key: str
    request_hash: str
    http_status: int
    receipt: LoadReceipt
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LoadResult:
    receipt: LoadReceipt
    replayed: bool
    http_status: int


def receipt_to_dict(receipt: LoadReceipt) -> dict[str, object]:
    return {
        "accepted": receipt.accepted,
        "duration_ms": receipt.duration_ms,
        "idempotency_key": receipt.idempotency_key,
        "inserted": receipt.inserted,
        "load_id": receipt.load_id,
        "rejected": receipt.rejected,
        "rejections": [
            {
                "code": item.code,
                "external_id": item.external_id,
                "message": item.message,
                "source_system": item.source_system,
            }
            for item in receipt.rejections
        ],
        "unchanged": receipt.unchanged,
        "updated": receipt.updated,
    }


def receipt_to_json(receipt: LoadReceipt) -> str:
    return json.dumps(receipt_to_dict(receipt), sort_keys=True, separators=(",", ":"))


def receipt_from_json(payload: str) -> LoadReceipt:
    data = json.loads(payload)
    rejections = tuple(
        Rejection(
            source_system=item["source_system"],
            external_id=item["external_id"],
            code=item["code"],
            message=item["message"],
        )
        for item in data["rejections"]
    )
    return LoadReceipt(
        load_id=data["load_id"],
        idempotency_key=data["idempotency_key"],
        accepted=int(data["accepted"]),
        rejected=int(data["rejected"]),
        inserted=int(data["inserted"]),
        updated=int(data["updated"]),
        unchanged=int(data["unchanged"]),
        duration_ms=int(data["duration_ms"]),
        rejections=rejections,
    )
