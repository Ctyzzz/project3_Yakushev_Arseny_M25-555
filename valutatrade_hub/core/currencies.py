from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from valutatrade_hub.core.exceptions import CurrencyNotFoundError
from valutatrade_hub.core.utils import validate_currency_code, validate_non_empty


@dataclass(frozen=True, slots=True)
class Currency(ABC):
    name: str
    code: str

    def __post_init__(self) -> None:
        validate_non_empty(self.name, "name")
        validate_currency_code(self.code)

    @abstractmethod
    def get_display_info(self) -> str: ...


@dataclass(frozen=True, slots=True)
class FiatCurrency(Currency):
    issuing_country: str

    def __post_init__(self) -> None:
        super(FiatCurrency, self).__post_init__()
        validate_non_empty(self.issuing_country, "issuing_country")

    def get_display_info(self) -> str:
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


@dataclass(frozen=True, slots=True)
class CryptoCurrency(Currency):
    algorithm: str
    market_cap: float

    def __post_init__(self) -> None:
        super(CryptoCurrency, self).__post_init__()
        validate_non_empty(self.algorithm, "algorithm")
        if not isinstance(self.market_cap, int | float) or self.market_cap < 0:
            raise ValueError("market_cap должен быть неотрицательным числом")

    def get_display_info(self) -> str:
        return f"[CRYPTO] {self.code} — {self.name} (Algo: {self.algorithm}, MCAP: {self.market_cap:.2e})"


# Реестр поддерживаемых валют
_REGISTRY: dict[str, Currency] = {
    "USD": FiatCurrency(name="US Dollar", code="USD", issuing_country="United States"),
    "EUR": FiatCurrency(name="Euro", code="EUR", issuing_country="Eurozone"),
    "GBP": FiatCurrency(name="British Pound", code="GBP", issuing_country="United Kingdom"),
    "RUB": FiatCurrency(name="Russian Ruble", code="RUB", issuing_country="Russia"),
    "BTC": CryptoCurrency(name="Bitcoin", code="BTC", algorithm="SHA-256", market_cap=1.12e12),
    "ETH": CryptoCurrency(name="Ethereum", code="ETH", algorithm="Ethash", market_cap=4.50e11),
    "SOL": CryptoCurrency(name="Solana", code="SOL", algorithm="PoH", market_cap=7.00e10),
}


def get_currency(code: str) -> Currency:
    code_u = code.upper().strip()
    if code_u not in _REGISTRY:
        raise CurrencyNotFoundError(code_u)
    return _REGISTRY[code_u]


def supported_codes() -> list[str]:
    return sorted(_REGISTRY.keys())
