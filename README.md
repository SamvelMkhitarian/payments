# Payments

Асинхронный сервис процессинга платежей на FastAPI, PostgreSQL, RabbitMQ и FastStream.

Сервис принимает запрос на создание платежа, сохраняет его в PostgreSQL, публикует событие через Outbox pattern, обрабатывает сообщение consumer-ом и отправляет webhook с результатом.

## Быстрый Старт

Требования:

- Docker и Docker Compose.

Запуск полного окружения:

```bash
docker compose up --build -d
```

Проверка API:

```bash
curl http://localhost:8000/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

RabbitMQ Management UI доступен по адресу http://localhost:15672.

Логин и пароль по умолчанию: `guest` / `guest`.

Остановка окружения:

```bash
docker compose down
```

## Переменные Окружения

Значения для локальной разработки описаны в `.env.example`.

```env
DATABASE_URL=postgresql+asyncpg://payments:payments@localhost:5432/payments
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
API_KEY=change-me
WEBHOOK_TIMEOUT_SECONDS=10
```

В Docker Compose `DATABASE_URL` и `RABBITMQ_URL` задаются контейнерными адресами автоматически. Для смены API-ключа можно создать `.env`:

```bash
cp .env.example .env
```

Затем изменить `API_KEY`.

## Примеры API

Во всех запросах к `/api/v1/*` обязателен заголовок `X-API-Key`.

Создать платеж:

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: change-me" \
  -H "Idempotency-Key: demo-payment-1" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.00",
    "currency": "RUB",
    "description": "Demo payment",
    "metadata": {"order_id": "order-1"},
    "webhook_url": "https://httpbin.org/post"
  }'
```

Успешный ответ возвращается со статусом `202 Accepted`:

```json
{
  "payment_id": "00000000-0000-0000-0000-000000000000",
  "status": "pending",
  "created_at": "2026-07-09T18:00:00.000000Z"
}
```

Получить платеж:

```bash
curl -i http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: change-me"
```

После обработки consumer-ом статус станет `succeeded` или `failed`, а поле `processed_at` будет заполнено.

Проверить идемпотентность:

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: change-me" \
  -H "Idempotency-Key: demo-payment-1" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.00",
    "currency": "RUB",
    "description": "Demo payment retry",
    "webhook_url": "https://httpbin.org/post"
  }'
```

Повторный запрос с тем же `Idempotency-Key` вернет тот же `payment_id` и не создаст дубль платежа.

## Локальная Разработка

Установить зависимости:

```bash
uv sync --dev
```

Линтеры и тайпчекер (как в CI):

```bash
uv run ruff check .
uv run flake8 .
uv run mypy .
uv run vulture
```

Тесты:

```bash
uv run pytest tests/ -v
```

Поднять PostgreSQL и RabbitMQ:

```bash
docker compose up -d postgres rabbitmq
```

Применить миграции:

```bash
uv run alembic upgrade head
```

Запустить API:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

В отдельных терминалах запустить outbox relay и consumer:

```bash
uv run python -m app.outbox
```

```bash
uv run python -m app.consumer
```

## Архитектура

Основной поток обработки:

```text
Client -> FastAPI -> PostgreSQL payments/outbox -> Outbox Relay -> RabbitMQ payments.new -> Consumer -> Webhook
```

Ключевые гарантии:

- `Idempotency-Key` защищает создание платежей от дублей.
- Outbox pattern публикует события только после commit транзакции API.
- RabbitMQ topology содержит очередь `payments.new`, retry-очереди и `payments.dlq`.
- Consumer эмулирует платёжный шлюз, обновляет статус платежа и отправляет webhook с retry.
