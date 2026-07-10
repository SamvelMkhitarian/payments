import asyncio
import logging
import signal
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import async_session_factory, engine
from app.messaging.broker import broker, declare_topology, payments_exchange
from app.models import Outbox, OutboxStatus

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
BATCH_SIZE = 10


async def run_relay(
    stop_event: asyncio.Event | None = None,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
) -> None:
    await broker.connect()
    try:
        await declare_topology()
        if stop_event is None:
            stop_event = asyncio.Event()

        while not stop_event.is_set():
            processed_count = await publish_pending_outbox()
            if processed_count == 0:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
                except TimeoutError:
                    pass
    finally:
        await broker.stop()
        await engine.dispose()


async def publish_pending_outbox(limit: int = BATCH_SIZE) -> int:
    async with async_session_factory() as session:
        try:
            async with session.begin():
                records = (
                    await session.execute(
                        select(Outbox)
                        .where(Outbox.status == OutboxStatus.PENDING)
                        .order_by(Outbox.created_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars().all()

                for record in records:
                    await broker.publish(
                        record.payload,
                        exchange=payments_exchange,
                        routing_key=record.event_type,
                        persist=True,
                    )
                    record.status = OutboxStatus.PROCESSED
                    record.processed_at = datetime.now(UTC)

                return len(records)
        except Exception:
            await session.rollback()
            logger.exception("Failed to publish pending outbox records")
            return 0


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
