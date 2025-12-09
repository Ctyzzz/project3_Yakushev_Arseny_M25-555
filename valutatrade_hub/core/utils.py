from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

T = TypeVar("T")

_CODE_RE = re.compile(r"^[A-Z]{2,5}$")


def validate_non_empty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} не может быть пустым")


def validate_currency_code(code: str) -> None:
    if not isinstance(code, str):
        raise TypeError("currency code должен быть строкой")
    c = code.strip().upper()
    if " " in c or not _CODE_RE.match(c):
        raise ValueError("code — верхний регистр, 2–5 символов, без пробелов")


def ensure_float_positive(value: Any, field: str) -> float:
    if not isinstance(value, int | float):
        raise TypeError(f"'{field}' должен быть числом")
    v = float(value)
    if v <= 0:
        raise ValueError(f"'{field}' должен быть положительным числом")
    return v


def iso_now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def isoformat_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(s: str) -> datetime:
    ss = s.replace("Z", "+00:00")
    return datetime.fromisoformat(ss)


def pair_key(from_code: str, to_code: str) -> str:
    return f"{from_code.upper()}_{to_code.upper()}"


def make_ttl_cache(ttl_seconds: int) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Замыкание для TTL-кэширования результатов функций.
    """
    ttl = max(0, int(ttl_seconds))

    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        cache: dict[tuple[Any, ...], tuple[float, T]] = {}

        def wrapped(*args: Any) -> T:
            now = time.monotonic()
            if args in cache:
                ts, val = cache[args]
                if now - ts <= ttl:
                    return val
            val = fn(*args)
            cache[args] = (now, val)
            return val

        return wrapped  # type: ignore[return-value]

    return deco
