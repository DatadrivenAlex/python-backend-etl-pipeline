"""Time the in-memory transform. No database and no network.

Run: python scripts/bench_transform.py
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl_pipeline.application.transform import InvoiceTransformer  # noqa: E402
from etl_pipeline.domain.models import Party, RawOrder, RawOrderLine  # noqa: E402


def main() -> None:
    transformer = InvoiceTransformer()
    orders = [_order(index) for index in range(5_000)]
    # Warm the rate card and dataclasses before the measured window.
    transformer.transform(orders[0])
    started = time.perf_counter()
    for order in orders:
        transformer.transform(order)
    elapsed = time.perf_counter() - started
    per_second = len(orders) / elapsed if elapsed else 0
    print(
        f"transformed {len(orders)} orders in {elapsed:.3f}s "
        f"({per_second:.0f} orders/s, pure Python, no I/O)"
    )


def _order(index: int) -> RawOrder:
    category = "reduced" if index % 2 else "standard"
    return RawOrder(
        source_system="erp-de",
        external_id=f"INV-{index}",
        ordered_at=datetime(2026, 1, 15, 8, 30, tzinfo=UTC),
        currency="EUR",
        seller=Party("SELL-1", "Nordlicht GmbH", "DE", "DE123456789"),
        buyer=Party("BUY-1", "Müller AG", "DE", "DE987654321"),
        lines=(
            RawOrderLine("SKU-1", "Copper busbar", Decimal("2"), Decimal("10.50"), "standard"),
            RawOrderLine("SKU-2", "Spare", Decimal("1.5"), Decimal("5.00"), category),
        ),
    )


if __name__ == "__main__":
    main()
