from collections.abc import Iterable

from aio_pika.abc import AbstractRobustExchange, AbstractRobustQueue
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.config import settings

PAYMENTS_EXCHANGE_NAME = "payments"
PAYMENTS_RETRY_EXCHANGE_NAME = "payments.retry"
PAYMENTS_DLX_EXCHANGE_NAME = "payments.dlx"

PAYMENT_CREATED_ROUTING_KEY = "payment.created"
PAYMENT_RETRY_ROUTING_KEYS = (
    "payment.retry.1",
    "payment.retry.2",
    "payment.retry.3",
)
PAYMENT_FAILED_ROUTING_KEY = "payment.failed"

RETRY_DELAYS_MS = (1_000, 2_000, 4_000)

broker = RabbitBroker(settings.rabbitmq_url)

payments_exchange = RabbitExchange(
    PAYMENTS_EXCHANGE_NAME,
    type=ExchangeType.DIRECT,
    durable=True,
)
payments_retry_exchange = RabbitExchange(
    PAYMENTS_RETRY_EXCHANGE_NAME,
    type=ExchangeType.DIRECT,
    durable=True,
)
payments_dlx_exchange = RabbitExchange(
    PAYMENTS_DLX_EXCHANGE_NAME,
    type=ExchangeType.DIRECT,
    durable=True,
)

payments_new_queue = RabbitQueue(
    "payments.new",
    durable=True,
    routing_key=PAYMENT_CREATED_ROUTING_KEY,
    arguments={
        "x-dead-letter-exchange": PAYMENTS_DLX_EXCHANGE_NAME,
        "x-dead-letter-routing-key": PAYMENT_FAILED_ROUTING_KEY,
    },
)

payments_dlq = RabbitQueue(
    "payments.dlq",
    durable=True,
    routing_key=PAYMENT_FAILED_ROUTING_KEY,
)

payments_retry_queues = tuple(
    RabbitQueue(
        f"payments.retry.{attempt}",
        durable=True,
        routing_key=routing_key,
        arguments={
            "x-message-ttl": delay_ms,
            "x-dead-letter-exchange": PAYMENTS_EXCHANGE_NAME,
            "x-dead-letter-routing-key": PAYMENT_CREATED_ROUTING_KEY,
        },
    )
    for attempt, (routing_key, delay_ms) in enumerate(
        zip(PAYMENT_RETRY_ROUTING_KEYS, RETRY_DELAYS_MS, strict=True),
        start=1,
    )
)


async def declare_topology() -> None:
    payments = await broker.declare_exchange(payments_exchange)
    retry = await broker.declare_exchange(payments_retry_exchange)
    dlx = await broker.declare_exchange(payments_dlx_exchange)

    await _declare_and_bind(payments_new_queue, payments)
    await _declare_and_bind(payments_dlq, dlx)

    for queue in payments_retry_queues:
        await _declare_and_bind(queue, retry)


async def _declare_and_bind(
    queue: RabbitQueue,
    exchange: AbstractRobustExchange,
) -> AbstractRobustQueue:
    declared_queue = await broker.declare_queue(queue)
    await declared_queue.bind(exchange, routing_key=queue.routing_key)
    return declared_queue


payment_queues: Iterable[RabbitQueue] = (
    payments_new_queue,
    payments_dlq,
    *payments_retry_queues,
)
