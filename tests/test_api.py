import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import get_session
from app.main import app


@pytest_asyncio.fixture
async def api_client(session_factory):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_payment_endpoint_returns_202(api_client):
    response = await api_client.post(
        "/api/v1/payments",
        headers={
            "X-API-Key": settings.api_key,
            "Idempotency-Key": "api-create-1",
        },
        json={
            "amount": "100.00",
            "currency": "RUB",
            "description": "api payment",
            "metadata": {"order_id": "order-1"},
            "webhook_url": "https://example.com/hook",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["payment_id"]
    assert body["created_at"]


@pytest.mark.asyncio
async def test_create_payment_requires_idempotency_key(api_client):
    response = await api_client.post(
        "/api/v1/payments",
        headers={"X-API-Key": settings.api_key},
        json={
            "amount": "100.00",
            "currency": "RUB",
            "description": "api payment",
            "webhook_url": "https://example.com/hook",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_api_requires_valid_api_key(api_client):
    response = await api_client.get(
        f"/api/v1/payments/{uuid.uuid4()}",
        headers={"X-API-Key": "invalid"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_payment_endpoint_returns_details(api_client):
    create_response = await api_client.post(
        "/api/v1/payments",
        headers={
            "X-API-Key": settings.api_key,
            "Idempotency-Key": "api-get-1",
        },
        json={
            "amount": "50.00",
            "currency": "EUR",
            "description": "lookup via api",
            "webhook_url": "https://example.com/hook",
        },
    )
    payment_id = create_response.json()["payment_id"]

    response = await api_client.get(
        f"/api/v1/payments/{payment_id}",
        headers={"X-API-Key": settings.api_key},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["payment_id"] == payment_id
    assert body["amount"] == "50.00"
    assert body["currency"] == "EUR"
    assert body["status"] == "pending"
    assert body["idempotency_key"] == "api-get-1"


@pytest.mark.asyncio
async def test_get_payment_endpoint_returns_404_for_missing_payment(api_client):
    response = await api_client.get(
        f"/api/v1/payments/{uuid.uuid4()}",
        headers={"X-API-Key": settings.api_key},
    )

    assert response.status_code == 404
