from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader


def _make_rotating_handler(path: Path, level: int, max_bytes: int, backup_count: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        filename=os.fspath(path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    return handler


def configure_logging() -> None:
    """
    Настройка логов:
    - ROOT: console (всё приложение)
    - valutatrade.actions: logs/actions.log (ротация), НЕ дублируем в консоли
    - valutatrade.parser: logs/parser.log (ротация) + ВЫВОД в консоль (propagate=True)

    RotatingFileHandler выбран из-за простоты и предсказуемости (размер + количество бэкапов).
    """
    settings = SettingsLoader()

    logs_dir = Path(str(settings.get("logs_dir", "logs")))
    logs_dir.mkdir(parents=True, exist_ok=True)

    level_name = str(settings.get("log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    max_bytes = int(settings.get("log_max_bytes", 1_048_576))
    backup_count = int(settings.get("log_backup_count", 5))

    fmt = "%(levelname)s %(asctime)s %(name)s: %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(level)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # actions -> только файл
    actions_logger = logging.getLogger("valutatrade.actions")
    actions_logger.setLevel(level)
    actions_logger.propagate = False
    actions_handler = _make_rotating_handler(logs_dir / "actions.log", level, max_bytes, backup_count)
    actions_handler.setFormatter(formatter)
    actions_logger.addHandler(actions_handler)

    # parser -> файл + консоль (через root)
    parser_logger = logging.getLogger("valutatrade.parser")
    parser_logger.setLevel(level)
    parser_logger.propagate = True
    parser_handler = _make_rotating_handler(logs_dir / "parser.log", level, max_bytes, backup_count)
    parser_handler.setFormatter(formatter)
    parser_logger.addHandler(parser_handler)
