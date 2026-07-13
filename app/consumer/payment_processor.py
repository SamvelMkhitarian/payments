import asyncio
import logging
import random
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.messaging.broker import (
    PAYMENT_WEBHOOK_ROUTING_KEY,
    broker,
    payments_exchange,
)
from app.messaging.utils import build_webhook_payload
from app.models import Payment, PaymentStatus

logger = logging.getLogger(__name__)

GATEWAY_DELAY_SECONDS = (2.0, 5.0)
GATEWAY_SUCCESS_RATE = 0.9


async def process_payment(payload: Mapping[str, Any]) -> None:
    payment_id = UUID(str(payload["payment_id"]))

    async with async_session_factory() as session:
        async with session.begin():
            payment = await _get_payment_for_update(session, payment_id)
            if payment is None:
                raise ValueError(f"Payment {payment_id} not found")
            if payment.status != PaymentStatus.PENDING:
                await _publish_webhook_event(payment)
                return

    await asyncio.sleep(random.uniform(*GATEWAY_DELAY_SECONDS))
    gateway_status = (
        PaymentStatus.SUCCEEDED
        if random.random() < GATEWAY_SUCCESS_RATE
        else PaymentStatus.FAILED
    )

    async with async_session_factory() as session:
        async with session.begin():
            payment = await _get_payment_for_update(session, payment_id)
            if payment is None:
                raise ValueError(f"Payment {payment_id} not found")
            if payment.status == PaymentStatus.PENDING:
                payment.status = gateway_status
                payment.processed_at = datetime.now(UTC)
            await _publish_webhook_event(payment)


async def _publish_webhook_event(payment: Payment) -> None:
    if payment.webhook_delivered_at is not None:
        return

    await broker.publish(
        build_webhook_payload(
            {
                "payment_id": payment.id,
                "webhook_url": payment.webhook_url,
                "status": payment.status.value,
                "amount": payment.amount,
                "currency": payment.currency.value,
                "processed_at": (
                    payment.processed_at.isoformat()
                    if payment.processed_at is not None
                    else None
                ),
            }
        ),
        exchange=payments_exchange,
        routing_key=PAYMENT_WEBHOOK_ROUTING_KEY,
        persist=True,
    )
    logger.info("Scheduled webhook delivery for payment %s", payment.id)


async def _get_payment_for_update(
    session: AsyncSession,
    payment_id: UUID,
) -> Payment | None:
    return await session.get(Payment, payment_id, with_for_update=True)
