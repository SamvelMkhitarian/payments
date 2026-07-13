import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class WebhookDeliveryError(Exception):
    """Retryable webhook delivery failure."""


class NonRetriableWebhookError(Exception):
    """Webhook endpoint rejected the request without retry."""


async def send_webhook_once(url: str, payload: Mapping[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        try:
            response = await client.post(url, json=dict(payload))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.exception("Webhook transport error for %s", url)
            raise WebhookDeliveryError from exc

    if response.is_success:
        logger.info("Webhook sent successfully to %s", url)
        return

    if _should_retry_response(response):
        logger.warning("Webhook failed with retriable status %s", response.status_code)
        raise WebhookDeliveryError(f"Webhook failed with status {response.status_code}")

    logger.warning("Webhook rejected with non-retriable status %s", response.status_code)
    raise NonRetriableWebhookError(f"Webhook failed with status {response.status_code}")


def _should_retry_response(response: httpx.Response) -> bool:
    return response.status_code == 429 or response.status_code >= 500
