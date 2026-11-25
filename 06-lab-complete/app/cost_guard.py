"""Atomically reserve a bounded mock cost and reconcile actual usage."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from redis import Redis

from utils.mock_llm import MOCK_RESPONSES

from .config import settings

# Nano-USD per estimated token. Each UTF-8 byte counts as one mock token.
INPUT_PRICE = 150
OUTPUT_PRICE = 600
MAX_OUTPUT_TOKENS = max(len(answer.encode()) for answers in MOCK_RESPONSES.values() for answer in answers)

RESERVE = """
local amount = tonumber(ARGV[1])
for i, key in ipairs(KEYS) do
    local used = tonumber(redis.call('GET', key) or '0')
    if amount > tonumber(ARGV[2 * i]) - used then
        return 0
    end
end
for i, key in ipairs(KEYS) do
    redis.call('INCRBY', key, ARGV[1])
    redis.call('EXPIREAT', key, ARGV[2 * i + 1])
end
return 1
"""

REFUND = """
for _, key in ipairs(KEYS) do
    if redis.call('EXISTS', key) == 1 then
        redis.call('DECRBY', key, ARGV[1])
    end
end
"""


@dataclass(frozen=True)
class Reservation:
    keys: tuple[str, ...]
    amount: int
    input_cost: int


def check_budget(client: Redis, question: str) -> Reservation:
    now = datetime.now(timezone.utc)
    next_day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    next_month = (now.replace(day=1) + timedelta(days=32)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    input_cost = len(question.encode()) * INPUT_PRICE
    amount = input_cost + MAX_OUTPUT_TOKENS * OUTPUT_PRICE
    keys = []
    arguments = [amount]
    for period, stamp, limit, end in (
        ("daily", now.strftime("%Y-%m-%d"), settings.daily_budget_nano_usd, next_day),
        ("monthly", now.strftime("%Y-%m"), settings.monthly_budget_nano_usd, next_month),
    ):
        if limit is not None:
            keys.append(f"day14:budget:{period}:{stamp}")
            # Retain old counters long enough for requests crossing a UTC boundary.
            arguments.extend((limit, int((end + timedelta(days=2)).timestamp())))
    if not client.eval(RESERVE, len(keys), *keys, *arguments):
        raise HTTPException(status_code=402, detail="Cost budget exhausted")
    return Reservation(tuple(keys), amount, input_cost)


def record_cost(client: Redis, reservation: Reservation, answer: str | None) -> int:
    actual = 0 if answer is None else reservation.input_cost + len(answer.encode()) * OUTPUT_PRICE
    if actual > reservation.amount:
        raise ValueError("Mock output exceeded its declared bound")
    refund = reservation.amount - actual
    if refund:
        client.eval(REFUND, len(reservation.keys), *reservation.keys, refund)
    return actual
