from app.messaging.broker import (
    PAYMENT_CREATED_ROUTING_KEY,
    PAYMENT_FAILED_ROUTING_KEY,
    PAYMENT_RETRY_ROUTING_KEYS,
    PAYMENT_WEBHOOK_FAILED_ROUTING_KEY,
    PAYMENT_WEBHOOK_ROUTING_KEY,
    PAYMENTS_DLX_EXCHANGE_NAME,
    PAYMENTS_EXCHANGE_NAME,
    PAYMENTS_RETRY_EXCHANGE_NAME,
    RETRY_DELAYS_MS,
    WEBHOOK_RETRY_ROUTING_KEYS,
    payment_queues,
    payments_dlq,
    payments_new_queue,
    payments_retry_queues,
    payments_webhook_dlq,
    payments_webhook_queue,
    webhook_retry_queues,
)


def test_payments_new_queue_configuration():
    assert payments_new_queue.name == "payments.new"
    assert payments_new_queue.routing_key == PAYMENT_CREATED_ROUTING_KEY
    assert payments_new_queue.arguments["x-dead-letter-exchange"] == PAYMENTS_RETRY_EXCHANGE_NAME
    assert payments_new_queue.arguments["x-dead-letter-routing-key"] == PAYMENT_RETRY_ROUTING_KEYS[0]


def test_payments_webhook_queue_configuration():
    assert payments_webhook_queue.name == "payments.webhook"
    assert payments_webhook_queue.routing_key == PAYMENT_WEBHOOK_ROUTING_KEY
    assert payments_webhook_queue.arguments["x-dead-letter-exchange"] == PAYMENTS_RETRY_EXCHANGE_NAME
    assert payments_webhook_queue.arguments["x-dead-letter-routing-key"] == WEBHOOK_RETRY_ROUTING_KEYS[0]


def test_payment_retry_queues_use_exponential_backoff_and_return_to_main_exchange():
    assert len(payments_retry_queues) == 3
    assert RETRY_DELAYS_MS == (1_000, 2_000, 4_000)

    for attempt, queue in enumerate(payments_retry_queues, start=1):
        assert queue.name == f"payments.retry.{attempt}"
        assert queue.routing_key == PAYMENT_RETRY_ROUTING_KEYS[attempt - 1]
        assert queue.arguments["x-dead-letter-exchange"] == PAYMENTS_EXCHANGE_NAME
        assert queue.arguments["x-dead-letter-routing-key"] == PAYMENT_CREATED_ROUTING_KEY
        assert queue.arguments["x-message-ttl"] == RETRY_DELAYS_MS[attempt - 1]


def test_webhook_retry_queues_use_exponential_backoff_and_return_to_webhook_queue():
    assert len(webhook_retry_queues) == 3

    for attempt, queue in enumerate(webhook_retry_queues, start=1):
        assert queue.name == f"payments.webhook.retry.{attempt}"
        assert queue.routing_key == WEBHOOK_RETRY_ROUTING_KEYS[attempt - 1]
        assert queue.arguments["x-dead-letter-exchange"] == PAYMENTS_EXCHANGE_NAME
        assert queue.arguments["x-dead-letter-routing-key"] == PAYMENT_WEBHOOK_ROUTING_KEY
        assert queue.arguments["x-message-ttl"] == RETRY_DELAYS_MS[attempt - 1]


def test_dlq_configuration():
    assert payments_dlq.name == "payments.dlq"
    assert payments_dlq.routing_key == PAYMENT_FAILED_ROUTING_KEY
    assert payments_webhook_dlq.name == "payments.webhook.dlq"
    assert payments_webhook_dlq.routing_key == PAYMENT_WEBHOOK_FAILED_ROUTING_KEY


def test_payment_queues_include_main_retry_and_dlq():
    queue_names = {queue.name for queue in payment_queues}
    assert queue_names == {
        "payments.new",
        "payments.webhook",
        "payments.dlq",
        "payments.webhook.dlq",
        "payments.retry.1",
        "payments.retry.2",
        "payments.retry.3",
        "payments.webhook.retry.1",
        "payments.webhook.retry.2",
        "payments.webhook.retry.3",
    }


def test_exchange_names():
    assert PAYMENTS_EXCHANGE_NAME == "payments"
    assert PAYMENTS_RETRY_EXCHANGE_NAME == "payments.retry"
    assert PAYMENTS_DLX_EXCHANGE_NAME == "payments.dlx"
