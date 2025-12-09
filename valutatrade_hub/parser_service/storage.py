from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from valutatrade_hub.core.utils import parse_dt
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.config import ParserConfig


@dataclass(slots=True)
class RatesStorage:
    cfg: ParserConfig
    db: DatabaseManager = field(init=False, repr=False)
    rates_path: Path = field(init=False, repr=False)
    history_path: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.db = DatabaseManager()
        self.rates_path = Path(self.cfg.RATES_FILE_PATH)
        self.history_path = Path(self.cfg.HISTORY_FILE_PATH)

    def write_snapshot(self, pairs: dict[str, dict[str, Any]], last_refresh: str) -> None:
        current = self.db.read_rates()
        cur_pairs = current.get("pairs", {})

        for k, v in pairs.items():
            if k not in cur_pairs:
                cur_pairs[k] = v
                continue

            old = cur_pairs[k]
            try:
                if parse_dt(v["updated_at"]) > parse_dt(old["updated_at"]):
                    cur_pairs[k] = v
            except Exception:  # noqa: BLE001
                cur_pairs[k] = v

        current["pairs"] = cur_pairs
        current["last_refresh"] = last_refresh
        self.db.write_rates(current)

    def append_history(self, entries: list[dict[str, Any]]) -> None:
        self.db.append_history(entries)
