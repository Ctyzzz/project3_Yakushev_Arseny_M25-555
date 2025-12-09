from __future__ import annotations

import logging
from typing import Any

from valutatrade_hub.core.utils import iso_now_utc
from valutatrade_hub.parser_service.api_clients import BaseApiClient
from valutatrade_hub.parser_service.storage import RatesStorage

_logger = logging.getLogger("valutatrade.parser")


class RatesUpdater:
    def __init__(self, clients: list[BaseApiClient], storage: RatesStorage) -> None:
        self.clients = clients
        self.storage = storage
        self.cfg = storage.cfg

    def run_update(self) -> dict[str, Any]:
        _logger.info("Starting rates update...")

        combined: dict[str, dict[str, Any]] = {}
        history_entries: list[dict[str, Any]] = []

        last_refresh = iso_now_utc()
        total = 0
        errors: list[str] = []
        sources: dict[str, dict[str, object]] = {}

        for client in self.clients:
            name = type(client).__name__
            try:
                _logger.info(f"Fetching from {name}...")
                rates = client.fetch_rates()

                meta = getattr(client, "last_meta", {})
                source = meta.get("source", name)
                updated_at = meta.get("timestamp", last_refresh)

                count = 0
                for pair, rate in rates.items():
                    combined[pair] = {"rate": float(rate), "updated_at": updated_at, "source": source}
                    count += 1

                    from_cur, to_cur = pair.split("_", maxsplit=1)
                    entry_id = f"{from_cur}_{to_cur}_{updated_at}"

                    extra = {
                        "raw_id": self.cfg.CRYPTO_ID_MAP.get(from_cur) if from_cur in self.cfg.CRYPTO_ID_MAP else None,
                        "request_ms": meta.get("request_ms"),
                        "status_code": meta.get("status_code"),
                        "etag": meta.get("etag"),
                    }
                    history_entries.append(
                        {
                            "id": entry_id,
                            "from_currency": from_cur,
                            "to_currency": to_cur,
                            "rate": float(rate),
                            "timestamp": updated_at,
                            "source": source,
                            "meta": extra,
                        }
                    )

                total += count
                sources[name] = {"ok": True, "count": count}
                _logger.info(f"{name} OK ({count} rates)")
            except Exception as e:  # noqa: BLE001
                err = f"Failed to fetch from {name}: {e}"
                errors.append(err)
                sources[name] = {"ok": False, "error": str(e)}
                _logger.error(err)

        if total == 0:
            raise RuntimeError("No rates fetched from any source")

        _logger.info(f"Writing {total} rates to data/rates.json...")
        self.storage.write_snapshot(combined, last_refresh=last_refresh)
        self.storage.append_history(history_entries)

        if errors:
            _logger.info("Update completed with errors.")
            return {
                "ok": False,
                "total": total,
                "last_refresh": last_refresh,
                "errors": errors,
                "sources": sources,
            }

        _logger.info("Update successful.")
        return {
            "ok": True,
            "total": total,
            "last_refresh": last_refresh,
            "errors": [],
            "sources": sources,
        }
