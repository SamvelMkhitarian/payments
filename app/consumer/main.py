import logging

from faststream import FastStream
from faststream.exceptions import AckMessage
from faststream.rabbit import RabbitMessage

from app.consumer.payment_processor import process_payment
from app.consumer.webhook_processor import deliver_webhook
from app.db import engine
from app.messaging.broker import (
    MAX_DELIVERY_ATTEMPTS,
    broker,
    declare_topology,
    payments_exchange,
    payments_new_queue,
    payments_webhook_queue,
)
from app.messaging.utils import delivery_count

logger = logging.getLogger(__name__)


async def shutdown() -> None:
    await engine.dispose()


def _ensure_retry_budget(message: RabbitMessage, queue_name: str) -> None:
    attempts = delivery_count(message)
    if attempts >= MAX_DELIVERY_ATTEMPTS:
        logger.error(
            "Message in %s exceeded retry budget (%s attempts)",
            queue_name,
            attempts,
        )
        raise AckMessage()


@broker.subscriber(payments_new_queue, payments_exchange)
async def process_payment_created(payload: dict, message: RabbitMessage) -> None:
    _ensure_retry_budget(message, payments_new_queue.name)
    await process_payment(payload)


@broker.subscriber(payments_webhook_queue, payments_exchange)
async def process_webhook_delivery(payload: dict, message: RabbitMessage) -> None:
    _ensure_retry_budget(message, payments_webhook_queue.name)
    await deliver_webhook(payload)


app = FastStream(
    broker,
    after_startup=[declare_topology],
    on_shutdown=[shutdown],
)


async def run() -> None:
    await app.run()
