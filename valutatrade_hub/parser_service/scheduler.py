from __future__ import annotations

import logging
import time
from collections.abc import Callable

_logger = logging.getLogger("valutatrade.parser")


def run_periodic(job: Callable[[], None], interval_seconds: int) -> None:
    interval = max(1, int(interval_seconds))
    _logger.info(f"Scheduler started, interval={interval}s")
    while True:
        try:
            job()
        except Exception as e:
            _logger.error(f"Scheduler job failed: {e}")
        time.sleep(interval)
