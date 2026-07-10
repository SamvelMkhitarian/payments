from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import Outbox, OutboxStatus
from app.outbox.relay import publish_pending_outbox
from app.schemas.payment import CreatePaymentRequest
from app.services.payment_service import create_payment


@pytest.mark.asyncio
async def test_publish_pending_outbox_publishes_and_marks_records_processed(
    patched_session_factory,
):
    request = CreatePaymentRequest(
        amount="25.00",
        currency="USD",
        description="outbox relay test",
        webhook_url="https://example.com/hook",
    )

    async with patched_session_factory() as session:
        await create_payment(session, "outbox-relay-1", request)

    publish = AsyncMock()
    with patch("app.outbox.relay.broker.publish", publish):
        processed_count = await publish_pending_outbox()

    assert processed_count == 1
    publish.assert_awaited_once()

    async with patched_session_factory() as session:
        outbox_record = await session.scalar(select(Outbox))
        assert outbox_record is not None
        assert outbox_record.status == OutboxStatus.PROCESSED
        assert outbox_record.processed_at is not None


@pytest.mark.asyncio
async def test_publish_pending_outbox_skips_already_processed_records(
    patched_session_factory,
):
    request = CreatePaymentRequest(
        amount="30.00",
        currency="EUR",
        description="outbox relay skip test",
        webhook_url="https://example.com/hook",
    )

    async with patched_session_factory() as session:
        await create_payment(session, "outbox-relay-2", request)

    publish = AsyncMock()
    with patch("app.outbox.relay.broker.publish", publish):
        first_count = await publish_pending_outbox()
        second_count = await publish_pending_outbox()

    assert first_count == 1
    assert second_count == 0
    publish.assert_awaited_once()
