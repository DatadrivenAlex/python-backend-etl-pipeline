import pytest
from fastapi.testclient import TestClient

from etl_pipeline.api.app import create_app
from etl_pipeline.config import Settings
from etl_pipeline.infrastructure.persistence.db import make_engine
from tests.conftest import api_order


@pytest.fixture
def client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        log_level="WARNING",
        db_startup_retries=0,
    )
    app = create_app(settings=settings, engine=engine)
    with TestClient(app) as test_client:
        yield test_client


def test_health_ready_and_metrics(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    assert client.get("/").json()["service"] == "python-backend-etl-pipeline"
    client.get("/health")
    body = client.get("/metrics").text
    assert 'etl_http_requests_total{method="GET",path="/health",status="200"}' in body
    assert "# TYPE etl_http_requests_total counter" in body


def test_ready_fails_when_the_database_is_down(client: TestClient) -> None:
    class _Down:
        def connect(self):
            raise RuntimeError("database down")

    client.app.state.runtime.engine = _Down()
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_idempotent_load_and_invoice_read(client: TestClient) -> None:
    payload = {"source_system": "erp-de", "orders": [api_order()]}
    headers = {"Idempotency-Key": "batch-0001"}
    created = client.post("/v1/loads", json=payload, headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["inserted"] == 1
    assert body["accepted"] == 1
    assert "replayed" not in body

    replay = client.post("/v1/loads", json=payload, headers=headers)
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["load_id"] == body["load_id"]
    assert replay.json()["inserted"] == 1

    invoice = client.get("/v1/invoices/erp-de/INV-100")
    assert invoice.status_code == 200
    document = invoice.json()
    assert document["net_total"] == {"amount": "21.00", "currency": "EUR"}
    assert document["vat_total"] == {"amount": "3.99", "currency": "EUR"}
    assert document["gross_total"] == {"amount": "24.99", "currency": "EUR"}
    assert isinstance(document["gross_total"]["amount"], str)
    assert document["lines"][0]["vat_code"] == "DE-STD"
    assert document["lines"][0]["vat_rate"] == "0.1900"
    assert document["buyer"]["name"] == "Müller AG"
    assert document["version"] == 1

    listing = client.get("/v1/invoices", params={"source_system": "erp-de"})
    assert listing.status_code == 200
    assert listing.json()[0]["external_id"] == "INV-100"
    assert listing.json()[0]["line_count"] == 1

    loaded = client.get(f"/v1/loads/{body['load_id']}")
    assert loaded.status_code == 200
    assert loaded.json()["load_id"] == body["load_id"]


def test_conflict_missing_key_and_not_found(client: TestClient) -> None:
    payload = {"source_system": "erp-de", "orders": [api_order()]}
    headers = {"Idempotency-Key": "batch-0009"}
    assert client.post("/v1/loads", json=payload, headers=headers).status_code == 201

    other = {"source_system": "erp-de", "orders": [api_order(external_id="INV-999")]}
    conflict = client.post("/v1/loads", json=other, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"

    missing_key = client.post("/v1/loads", json=payload)
    assert missing_key.status_code == 422

    naive = client.post(
        "/v1/loads",
        json={
            "source_system": "erp-de",
            "orders": [api_order(ordered_at="2026-01-15T08:30:00")],
        },
        headers={"Idempotency-Key": "batch-0010"},
    )
    assert naive.status_code == 422

    assert client.get("/v1/invoices/erp-de/MISSING").status_code == 404
    assert client.get("/v1/loads/not-a-uuid").status_code == 404


def test_business_rejection_is_still_a_successful_load(client: TestClient) -> None:
    bad = api_order(external_id="INV-BAD")
    bad["lines"] = [
        {
            "sku": "SKU-X",
            "description": "Broken qty",
            "quantity": "-1",
            "unit_price": "10.00",
            "vat_category": "standard",
        }
    ]
    response = client.post(
        "/v1/loads",
        json={"source_system": "erp-de", "orders": [api_order(), bad]},
        headers={"Idempotency-Key": "batch-0011"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["accepted"] == 1
    assert body["rejected"] == 1
    assert body["rejections"][0]["code"] == "INVALID_QUANTITY"
