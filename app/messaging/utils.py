from collections.abc import Mapping
from typing import Any

from faststream.rabbit import RabbitMessage


def delivery_count(message: RabbitMessage) -> int:
    deaths = message.headers.get("x-death")
    if not isinstance(deaths, list):
        return 0
    return sum(int(entry.get("count", 0)) for entry in deaths if isinstance(entry, dict))


def build_webhook_payload(payment_data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "payment_id": str(payment_data["payment_id"]),
        "webhook_url": str(payment_data["webhook_url"]),
        "status": payment_data["status"],
        "amount": str(payment_data["amount"]),
        "currency": str(payment_data["currency"]),
        "processed_at": payment_data.get("processed_at"),
    }
