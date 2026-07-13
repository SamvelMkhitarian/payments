from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.consumer.payment_processor import process_payment
from app.messaging.broker import PAYMENT_WEBHOOK_ROUTING_KEY, payments_exchange
from app.models import Currency, Payment, PaymentStatus


async def _create_payment(
    session_factory,
    *,
    status=PaymentStatus.PENDING,
    webhook_delivered_at=None,
):
    payment = Payment(
        id=uuid4(),
        amount=Decimal("100.00"),
        currency=Currency.RUB,
        description="consumer test",
        metadata_={},
        status=status,
        idempotency_key=f"consumer-{uuid4()}",
        webhook_url="https://example.com/hook",
        created_at=datetime.now(UTC),
        processed_at=datetime.now(UTC) if status != PaymentStatus.PENDING else None,
        webhook_delivered_at=webhook_delivered_at,
    )
    async with session_factory() as session:
        async with session.begin():
            session.add(payment)
    return payment


@pytest.mark.asyncio
async def test_process_payment_updates_pending_payment_and_schedules_webhook(
    patched_session_factory,
):
    payment = await _create_payment(patched_session_factory)
    publish = AsyncMock()

    with (
        patch("app.consumer.payment_processor.asyncio.sleep", new=AsyncMock()),
        patch("app.consumer.payment_processor.random.uniform", return_value=3.0),
        patch("app.consumer.payment_processor.random.random", return_value=0.0),
        patch("app.consumer.payment_processor.broker.publish", publish),
    ):
        await process_payment({"payment_id": str(payment.id)})

    publish.assert_awaited_once()
    kwargs = publish.await_args.kwargs
    assert kwargs["exchange"] == payments_exchange
    assert kwargs["routing_key"] == PAYMENT_WEBHOOK_ROUTING_KEY

    async with patched_session_factory() as session:
        updated = await session.get(Payment, payment.id)
        assert updated is not None
        assert updated.status == PaymentStatus.SUCCEEDED
        assert updated.processed_at is not None
        assert updated.webhook_delivered_at is None


@pytest.mark.asyncio
async def test_process_payment_schedules_webhook_for_already_processed_payment(
    patched_session_factory,
):
    payment = await _create_payment(
        patched_session_factory,
        status=PaymentStatus.SUCCEEDED,
    )
    publish = AsyncMock()

    with (
        patch("app.consumer.payment_processor.asyncio.sleep", new=AsyncMock()) as sleep_mock,
        patch("app.consumer.payment_processor.broker.publish", publish),
    ):
        await process_payment({"payment_id": str(payment.id)})

    sleep_mock.assert_not_awaited()
    publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_payment_skips_webhook_event_when_already_delivered(
    patched_session_factory,
):
    payment = await _create_payment(
        patched_session_factory,
        status=PaymentStatus.SUCCEEDED,
        webhook_delivered_at=datetime.now(UTC),
    )
    publish = AsyncMock()

    with patch("app.consumer.payment_processor.broker.publish", publish):
        await process_payment({"payment_id": str(payment.id)})

    publish.assert_not_awaited()
