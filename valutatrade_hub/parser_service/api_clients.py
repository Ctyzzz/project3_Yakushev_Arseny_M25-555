from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import isoformat_dt, pair_key, validate_currency_code
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    @abstractmethod
    def fetch_rates(self) -> dict[str, float]: ...


class CoinGeckoClient(BaseApiClient):
    def __init__(self, cfg: ParserConfig) -> None:
        self.cfg = cfg
        self.last_meta: dict[str, Any] = {}

    def fetch_rates(self) -> dict[str, float]:
        ids = [self.cfg.CRYPTO_ID_MAP[c] for c in self.cfg.CRYPTO_CURRENCIES if c in self.cfg.CRYPTO_ID_MAP]
        params = {"ids": ",".join(ids), "vs_currencies": self.cfg.BASE_CURRENCY.lower()}

        t0 = time.perf_counter()
        try:
            resp = requests.get(self.cfg.COINGECKO_URL, params=params, timeout=self.cfg.REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            raise ApiRequestError(f"CoinGecko network error: {e}") from e
        ms = int((time.perf_counter() - t0) * 1000)

        if resp.status_code == 429:
            raise ApiRequestError("CoinGecko: 429 Too Many Requests (лимит запросов)")
        if 500 <= resp.status_code <= 599:
            raise ApiRequestError(f"CoinGecko: server error {resp.status_code}")
        if resp.status_code != 200:
            raise ApiRequestError(f"CoinGecko: status={resp.status_code}: {resp.text[:200]}")

        etag = resp.headers.get("ETag")
        now = datetime.now(UTC).replace(microsecond=0)

        data = resp.json()
        out: dict[str, float] = {}

        for code in self.cfg.CRYPTO_CURRENCIES:
            coin_id = self.cfg.CRYPTO_ID_MAP.get(code)
            if not coin_id:
                continue
            if coin_id in data and self.cfg.BASE_CURRENCY.lower() in data[coin_id]:
                validate_currency_code(code)
                rate = float(data[coin_id][self.cfg.BASE_CURRENCY.lower()])
                out[pair_key(code, self.cfg.BASE_CURRENCY)] = rate

        self.last_meta = {
            "source": "CoinGecko",
            "timestamp": isoformat_dt(now),
            "request_ms": ms,
            "status_code": resp.status_code,
            "etag": etag,
        }
        return out


class ExchangeRateApiClient(BaseApiClient):
    def __init__(self, cfg: ParserConfig) -> None:
        self.cfg = cfg
        self.last_meta: dict[str, Any] = {}

    def fetch_rates(self) -> dict[str, float]:
        if not self.cfg.EXCHANGERATE_API_KEY:
            raise ApiRequestError("ExchangeRate-API key is missing (set EXCHANGERATE_API_KEY env var)")

        url = f"{self.cfg.EXCHANGERATE_API_URL}/{self.cfg.EXCHANGERATE_API_KEY}/latest/{self.cfg.BASE_CURRENCY}"

        t0 = time.perf_counter()
        try:
            resp = requests.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            raise ApiRequestError(f"ExchangeRate-API network error: {e}") from e
        ms = int((time.perf_counter() - t0) * 1000)

        if resp.status_code in (401, 403):
            raise ApiRequestError("ExchangeRate-API: неверный/заблокированный API ключ (401/403)")
        if resp.status_code == 429:
            raise ApiRequestError("ExchangeRate-API: 429 Too Many Requests (лимит запросов)")
        if 500 <= resp.status_code <= 599:
            raise ApiRequestError(f"ExchangeRate-API: server error {resp.status_code}")
        if resp.status_code != 200:
            raise ApiRequestError(f"ExchangeRate-API: status={resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        if data.get("result") != "success":
            raise ApiRequestError(f"ExchangeRate-API error: {data.get('error-type', 'unknown')}")

        rates = data.get("rates", {})
        utc_str = data.get("time_last_update_utc")
        if utc_str:
            dt = parsedate_to_datetime(utc_str).astimezone(UTC).replace(microsecond=0)
        else:
            dt = datetime.now(UTC).replace(microsecond=0)

        # API отдаёт rates по базе USD: 1 USD = rates[EUR] EUR.
        # Нам нужно EUR_USD: 1 EUR = 1/rates[EUR] USD.
        out: dict[str, float] = {}
        for code in self.cfg.FIAT_CURRENCIES:
            validate_currency_code(code)
            if code == self.cfg.BASE_CURRENCY:
                continue
            raw = rates.get(code)
            if raw is None:
                continue
            value = float(raw)
            if value == 0:
                continue
            out[pair_key(code, self.cfg.BASE_CURRENCY)] = 1.0 / value

        self.last_meta = {
            "source": "ExchangeRate-API",
            "timestamp": isoformat_dt(dt),
            "request_ms": ms,
            "status_code": resp.status_code,
            "etag": resp.headers.get("ETag"),
        }
        return out
