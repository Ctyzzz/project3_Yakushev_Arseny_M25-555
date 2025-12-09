from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

T = TypeVar("T")

_actions_logger = logging.getLogger("valutatrade.actions")


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log_action(action: str, verbose: bool = False) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Декоратор логирования доменных операций.
    """

    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            ts = _iso_now()

            try:
                result = fn(*args, **kwargs)
                payload: dict[str, Any] = result if isinstance(result, dict) else {"result": "OK"}

                msg = (
                    f"{ts} {action} "
                    f"user='{payload.get('username', payload.get('user_id', 'unknown'))}' "
                    f"currency='{payload.get('currency_code', '-')}' "
                    f"amount={payload.get('amount', '-')}"
                )

                if "rate" in payload and "base" in payload:
                    msg += f" rate={payload['rate']} base='{payload['base']}'"

                msg += " result=OK"

                if verbose and "before_after" in payload:
                    msg += f" ctx={payload['before_after']}"

                _actions_logger.info(msg)
                return result
            except Exception as e:  # noqa: BLE001
                err_type = type(e).__name__
                err_msg = str(e)
                msg = f"{ts} {action} result=ERROR error_type={err_type} error_message={err_msg}"
                _actions_logger.error(msg)
                raise

        return wrapper

    return deco
