"""Map HTTP models to domain objects and back. No pricing happens here."""

from __future__ import annotations

from etl_pipeline.api.schemas import (
    InvoiceLineOut,
    InvoiceOut,
    InvoiceSummaryOut,
    LoadRequest,
    LoadResponse,
    MoneyOut,
    PartyOut,
    RejectionOut,
)
from etl_pipeline.application.receipts import LoadReceipt
from etl_pipeline.domain.models import (
    Invoice,
    InvoiceSummary,
    Party,
    RawOrder,
    RawOrderLine,
    request_fingerprint,
)
from etl_pipeline.domain.money import Money, format_decimal
from etl_pipeline.domain.time import ensure_utc


def orders_from_request(payload: LoadRequest) -> list[RawOrder]:
    orders: list[RawOrder] = []
    for order in payload.orders:
        orders.append(
            RawOrder(
                source_system=payload.source_system,
                external_id=order.external_id,
                ordered_at=ensure_utc(order.ordered_at),
                currency=order.currency.upper(),
                seller=_party_in(order.seller),
                buyer=_party_in(order.buyer),
                lines=tuple(
                    RawOrderLine(
                        sku=line.sku,
                        description=line.description,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                        vat_category=line.vat_category,
                    )
                    for line in order.lines
                ),
            )
        )
    return orders


def request_hash(payload: LoadRequest, orders: list[RawOrder]) -> str:
    return request_fingerprint(payload.source_system, orders)


def load_response(receipt: LoadReceipt) -> LoadResponse:
    return LoadResponse(
        load_id=receipt.load_id,
        idempotency_key=receipt.idempotency_key,
        accepted=receipt.accepted,
        rejected=receipt.rejected,
        inserted=receipt.inserted,
        updated=receipt.updated,
        unchanged=receipt.unchanged,
        duration_ms=receipt.duration_ms,
        rejections=[
            RejectionOut(
                source_system=item.source_system,
                external_id=item.external_id,
                code=item.code,
                message=item.message,
            )
            for item in receipt.rejections
        ],
    )


def invoice_response(invoice: Invoice) -> InvoiceOut:
    return InvoiceOut(
        source_system=invoice.source_system,
        external_id=invoice.external_id,
        ordered_at=invoice.ordered_at,
        currency=invoice.currency,
        seller=_party_out(invoice.seller),
        buyer=_party_out(invoice.buyer),
        lines=[_line_out(line) for line in invoice.lines],
        net_total=_money_out(invoice.net_total),
        vat_total=_money_out(invoice.vat_total),
        gross_total=_money_out(invoice.gross_total),
        content_hash=invoice.content_hash,
        version=invoice.version,
    )


def summary_response(summary: InvoiceSummary) -> InvoiceSummaryOut:
    return InvoiceSummaryOut(
        source_system=summary.source_system,
        external_id=summary.external_id,
        ordered_at=summary.ordered_at,
        currency=summary.currency,
        net_total=_money_out(summary.net_total),
        vat_total=_money_out(summary.vat_total),
        gross_total=_money_out(summary.gross_total),
        version=summary.version,
        line_count=summary.line_count,
    )


def _party_in(party) -> Party:
    vat_id = party.vat_id.strip() if party.vat_id else None
    return Party(
        party_id=party.party_id.strip(),
        name=party.name,
        country=party.country,
        vat_id=vat_id or None,
    )


def _party_out(party: Party) -> PartyOut:
    return PartyOut(
        party_id=party.party_id,
        name=party.name,
        country=party.country,
        vat_id=party.vat_id,
    )


def _line_out(line) -> InvoiceLineOut:
    return InvoiceLineOut(
        line_no=line.line_no,
        sku=line.sku,
        description=line.description,
        quantity=format_decimal(line.quantity, 3),
        unit_net=MoneyOut(
            amount=format_decimal(line.unit_net.amount, 4),
            currency=line.unit_net.currency,
        ),
        line_net=_money_out(line.line_net),
        vat_code=line.vat_code,
        vat_rate=format_decimal(line.vat_rate, 4),
        vat_treatment=line.vat_treatment,
        vat_amount=_money_out(line.vat_amount),
        line_gross=_money_out(line.line_gross),
    )


def _money_out(money: Money) -> MoneyOut:
    return MoneyOut(amount=format_decimal(money.amount, 2), currency=money.currency)
