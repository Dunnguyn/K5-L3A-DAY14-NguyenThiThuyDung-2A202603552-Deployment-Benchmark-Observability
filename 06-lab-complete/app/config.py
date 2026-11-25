"""Validated environment configuration. Process variables override the local dotenv."""

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext

from dotenv import load_dotenv

NANO_USD_PER_USD = 1_000_000_000

load_dotenv(override=False)


def env_int(name: str, default: str, maximum: int) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} is outside its supported range")
    return value


def env_budget(name: str, default: str) -> int | None:
    raw = os.getenv(name, default).strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{name} must be a decimal amount in USD") from None
    # Stay inside Lua's exact integer range after conversion to nano-USD.
    if not value.is_finite() or not 0 <= value <= 1_000_000:
        raise ValueError(f"{name} must be finite and between 0 and 1000000 USD")
    with localcontext() as context:
        context.prec = max(context.prec, len(value.as_tuple().digits))
        if value < Decimal("0.000000001"):
            return 0
        return int((value * NANO_USD_PER_USD).to_integral_value(rounding=ROUND_FLOOR))


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: env_int("PORT", "8000", 65535))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""), repr=False)
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), repr=False)
    rate_limit_per_minute: int = field(default_factory=lambda: env_int("RATE_LIMIT_PER_MINUTE", "10", 1_000_000))
    daily_budget_nano_usd: int | None = field(default_factory=lambda: env_budget("DAILY_BUDGET_USD", "1.00"))
    monthly_budget_nano_usd: int | None = field(default_factory=lambda: env_budget("MONTHLY_BUDGET_USD", ""))

    def __post_init__(self) -> None:
        if self.daily_budget_nano_usd is None and self.monthly_budget_nano_usd is None:
            raise ValueError("Configure at least one cost budget")


settings = Settings()
