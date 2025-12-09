from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import (
    ensure_float_positive,
    isoformat_dt,
    parse_dt,
    validate_currency_code,
    validate_non_empty,
)


@dataclass(slots=True)
class User:
    _user_id: int
    _username: str
    _hashed_password: str
    _salt: str
    _registration_date: datetime

    def __post_init__(self) -> None:
        if not isinstance(self._user_id, int) or self._user_id <= 0:
            raise ValueError("user_id должен быть положительным int")
        validate_non_empty(self._username, "username")
        validate_non_empty(self._hashed_password, "hashed_password")
        validate_non_empty(self._salt, "salt")
        if not isinstance(self._registration_date, datetime):
            raise TypeError("registration_date должен быть datetime")

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        validate_non_empty(value, "username")
        self._username = value

    @property
    def salt(self) -> str:
        return self._salt

    @property
    def registration_date(self) -> datetime:
        return self._registration_date

    def get_user_info(self) -> dict[str, Any]:
        return {
            "user_id": self._user_id,
            "username": self._username,
            "registration_date": isoformat_dt(self._registration_date),
        }

    def _hash_password(self, password: str, salt: str) -> str:
        validate_non_empty(password, "password")
        if len(password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")
        data = (password + salt).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def change_password(self, new_password: str) -> None:
        new_salt = secrets.token_urlsafe(8)
        self._salt = new_salt
        self._hashed_password = self._hash_password(new_password, new_salt)

    def verify_password(self, password: str) -> bool:
        try:
            return self._hash_password(password, self._salt) == self._hashed_password
        except ValueError:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self._user_id,
            "username": self._username,
            "hashed_password": self._hashed_password,
            "salt": self._salt,
            "registration_date": isoformat_dt(self._registration_date),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> User:
        return cls(
            _user_id=int(d["user_id"]),
            _username=str(d["username"]),
            _hashed_password=str(d["hashed_password"]),
            _salt=str(d["salt"]),
            _registration_date=parse_dt(str(d["registration_date"])),
        )


@dataclass(slots=True)
class Wallet:
    currency_code: str
    _balance: float = 0.0

    def __post_init__(self) -> None:
        validate_currency_code(self.currency_code)
        self.balance = self._balance

    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        if not isinstance(value, int | float):
            raise TypeError("balance должен быть числом")
        if value < 0:
            raise ValueError("balance не может быть отрицательным")
        self._balance = float(value)

    def deposit(self, amount: float) -> None:
        ensure_float_positive(amount, "amount")
        self.balance = self.balance + float(amount)

    def withdraw(self, amount: float) -> None:
        ensure_float_positive(amount, "amount")
        if amount > self.balance:
            raise InsufficientFundsError(available=self.balance, required=amount, code=self.currency_code)
        self.balance = self.balance - float(amount)

    def get_balance_info(self) -> str:
        return f"{self.currency_code}: {self.balance:.4f}"

    def to_dict(self) -> dict[str, Any]:
        return {"currency_code": self.currency_code, "balance": self.balance}

    @classmethod
    def from_dict(cls, code: str, d: dict[str, Any]) -> Wallet:
        bal = float(d.get("balance", 0.0))
        return cls(currency_code=code, _balance=bal)


@dataclass(slots=True)
class Portfolio:
    _user_id: int
    _wallets: dict[str, Wallet]

    def __post_init__(self) -> None:
        if not isinstance(self._user_id, int) or self._user_id <= 0:
            raise ValueError("user_id должен быть положительным int")
        if not isinstance(self._wallets, dict):
            raise TypeError("wallets должен быть dict")

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def wallets(self) -> dict[str, Wallet]:
        return dict(self._wallets)

    def add_currency(self, currency_code: str) -> Wallet:
        validate_currency_code(currency_code)
        code = currency_code.upper()
        if code in self._wallets:
            return self._wallets[code]
        w = Wallet(currency_code=code, _balance=0.0)
        self._wallets[code] = w
        return w

    def get_wallet(self, currency_code: str) -> Wallet | None:
        code = currency_code.upper().strip()
        return self._wallets.get(code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self._user_id,
            "wallets": {code: {"balance": w.balance} for code, w in self._wallets.items()},
        }
    
    def get_total_value(self, base_currency: str = "USD", exchange_rates: dict[str, float] | None = None) -> float:
        base = base_currency.upper().strip()
        if exchange_rates is None:
            exchange_rates = {
                "USD_USD": 1.0,
                "EUR_USD": 1.0786,
                "GBP_USD": 1.25,
                "RUB_USD": 0.01016,
                "BTC_USD": 59337.21,
                "ETH_USD": 3720.0,
                "SOL_USD": 145.12,
            }

        def rate(frm: str, to: str) -> float | None:
            k = f"{frm}_{to}"
            if k in exchange_rates:
                return float(exchange_rates[k])
            rk = f"{to}_{frm}"
            if rk in exchange_rates and float(exchange_rates[rk]) != 0:
                return 1.0 / float(exchange_rates[rk])
            # мост через USD
            if frm != "USD" and to != "USD":
                r1 = rate(frm, "USD")
                r2 = rate(to, "USD")
                if r1 is not None and r2 is not None and r2 != 0:
                    return r1 / r2
            return None

        total = 0.0
        for code, w in self._wallets.items():
            if code == base:
                total += w.balance
                continue
            r = rate(code, base)
            if r is not None:
                total += w.balance * r
        return total


    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Portfolio:
        wallets_raw = d.get("wallets", {})
        wallets: dict[str, Wallet] = {}
        for code, payload in wallets_raw.items():
            wallets[code] = Wallet.from_dict(code, payload)
        return cls(_user_id=int(d["user_id"]), _wallets=wallets)
