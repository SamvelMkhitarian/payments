import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.models import Payment
from app.services.webhook_service import NonRetriableWebhookError, send_webhook_once

logger = logging.getLogger(__name__)


async def deliver_webhook(payload: dict[str, Any]) -> None:
    payment_id = UUID(str(payload["payment_id"]))

    async with async_session_factory() as session:
        async with session.begin():
            payment = await _get_payment_for_update(session, payment_id)
            if payment is not None and payment.webhook_delivered_at is not None:
                return

    try:
        await send_webhook_once(str(payload["webhook_url"]), payload)
    except NonRetriableWebhookError:
        logger.warning("Webhook for payment %s rejected with non-retriable status", payment_id)
        return

    async with async_session_factory() as session:
        async with session.begin():
            payment = await _get_payment_for_update(session, payment_id)
            if payment is not None and payment.webhook_delivered_at is None:
                payment.webhook_delivered_at = datetime.now(UTC)


async def _get_payment_for_update(
    session: AsyncSession,
    payment_id: UUID,
) -> Payment | None:
    return await session.get(Payment, payment_id, with_for_update=True)
