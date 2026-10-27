from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from etl_pipeline.application.errors import IdempotencyConflict
from etl_pipeline.composition import build_runtime
from etl_pipeline.config import Settings
from etl_pipeline.domain.money import Money
from etl_pipeline.infrastructure.persistence.db import build_session_factory, make_engine
from etl_pipeline.infrastructure.persistence.orm import InvoiceRow, RejectionRow
from tests.conftest import line, order


@pytest.fixture
def runtime():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        log_level="WARNING",
        db_startup_retries=0,
    )
    return build_runtime(settings, engine=engine)


def test_insert_replay_unchanged_and_update(runtime) -> None:
    service = runtime.load_service()
    first = service.execute([order()], idempotency_key="batch-0001", request_hash="hash-a")
    assert first.replayed is False
    assert first.http_status == 201
    assert first.receipt.inserted == 1
    assert first.receipt.accepted == 1

    replay = service.execute([order()], idempotency_key="batch-0001", request_hash="hash-a")
    assert replay.replayed is True
    assert replay.receipt.load_id == first.receipt.load_id

    again = service.execute(
        [order()],
        idempotency_key="batch-0002",
        request_hash="hash-b",
    )
    assert again.receipt.unchanged == 1
    assert again.receipt.inserted == 0

    updated = service.execute(
        [order(lines=(line(unit_price="11.00"),))],
        idempotency_key="batch-0003",
        request_hash="hash-c",
    )
    assert updated.receipt.updated == 1
    stored = service.get_invoice("erp-de", "INV-100")
    assert stored is not None
    assert stored.version == 2
    assert stored.gross_total == Money(Decimal("26.18"), "EUR")
    assert stored.content_hash

    with pytest.raises(IdempotencyConflict):
        service.execute(
            [order(lines=(line(unit_price="12.00"),))],
            idempotency_key="batch-0001",
            request_hash="hash-other",
        )

    # The conflicting call must not have changed the row.
    stored_after = service.get_invoice("erp-de", "INV-100")
    assert stored_after is not None
    assert stored_after.version == 2
    assert _count(runtime, InvoiceRow) == 1


def test_rejections_are_stored_and_siblings_still_load(runtime) -> None:
    service = runtime.load_service()
    result = service.execute(
        [order(), order(external_id="INV-BAD", lines=(line(quantity="-1"),))],
        idempotency_key="batch-0004",
        request_hash="hash-d",
    )
    assert result.receipt.accepted == 1
    assert result.receipt.rejected == 1
    assert result.receipt.rejections[0].code == "INVALID_QUANTITY"
    assert _count(runtime, RejectionRow) == 1
    assert service.get_invoice("erp-de", "INV-BAD") is None
    assert service.get_load(result.receipt.load_id) is not None


def test_duplicate_external_id_in_one_batch_keeps_the_first(runtime) -> None:
    service = runtime.load_service()
    result = service.execute(
        [order(), order(lines=(line(unit_price="99.00"),))],
        idempotency_key="batch-0005",
        request_hash="hash-e",
    )
    assert result.receipt.accepted == 1
    assert result.receipt.rejections[0].code == "DUPLICATE_IN_BATCH"
    stored = service.get_invoice("erp-de", "INV-100")
    assert stored is not None
    assert stored.net_total == Money(Decimal("21.00"), "EUR")


def _count(runtime, model) -> int:
    factory = build_session_factory(runtime.engine)
    session: Session = factory()
    try:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)
    finally:
        session.close()
