from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from valutatrade_hub.core.currencies import get_currency, supported_codes
from valutatrade_hub.core.exceptions import ApiRequestError, CurrencyNotFoundError
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import (
    ensure_float_positive,
    make_ttl_cache,
    pair_key,
    parse_dt,
    validate_currency_code,
    validate_non_empty,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


class CoreUseCases:
    def __init__(self) -> None:
        self.db = DatabaseManager()
        self.settings = SettingsLoader()

        ttl = int(self.settings.get("rates_ttl_seconds", 300))
        self._cached_rates = self._build_rates_reader(ttl)

    def _build_rates_reader(self, ttl: int):
        @make_ttl_cache(ttl_seconds=max(1, ttl))
        def _read_rates_snapshot() -> dict:
            return self.db.read_rates()

        return _read_rates_snapshot

    # -------- auth --------
    def register(self, username: str, password: str) -> str:
        validate_non_empty(username, "username")
        validate_non_empty(password, "password")
        if len(password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")

        if self.db.find_user_by_username(username) is not None:
            raise ValueError(f"Имя пользователя '{username}' уже занято")

        user_id = self.db.next_user_id()
        salt = secrets.token_urlsafe(8)
        hashed = hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

        reg_dt = datetime.now(UTC).replace(microsecond=0)

        user = User(
            _user_id=user_id,
            _username=username,
            _hashed_password=hashed,
            _salt=salt,
            _registration_date=reg_dt,
        )

        self.db.append_user(user.to_dict())

        self.db.upsert_portfolio({"user_id": user_id, "wallets": {}})

        return f"Пользователь '{username}' зарегистрирован (id={user_id}). Войдите: login --username {username} --password ****"

    def login(self, username: str, password: str) -> str:
        validate_non_empty(username, "username")
        validate_non_empty(password, "password")

        u = self.db.find_user_by_username(username)
        if u is None:
            raise ValueError(f"Пользователь '{username}' не найден")

        user = User.from_dict(u)
        if not user.verify_password(password):
            raise ValueError("Неверный пароль")

        # Сессионное состояние
        self.db.set_session({"user_id": user.user_id, "username": user.username})

        self._ensure_initial_usd(user.user_id)

        return f"Вы вошли как '{username}'"

    def logout(self) -> str:
        self.db.clear_session()
        return "Вы вышли из системы"

    def current_user(self) -> dict | None:
        s = self.db.get_session()
        return s if s.get("user_id") else None

    def _ensure_initial_usd(self, user_id: int) -> None:
        initial = float(self.settings.get("initial_usd_balance", 0.0))
        p = self.db.get_portfolio(user_id) or {"user_id": user_id, "wallets": {}}
        wallets = p.get("wallets", {})
        if "USD" not in wallets and initial > 0:
            wallets["USD"] = {"balance": initial}
            p["wallets"] = wallets
            self.db.upsert_portfolio(p)

    # -------- portfolio --------
    def load_portfolio(self, user_id: int) -> Portfolio:
        p = self.db.get_portfolio(user_id)
        if p is None:
            p = {"user_id": user_id, "wallets": {}}
            self.db.upsert_portfolio(p)
        return Portfolio.from_dict(p)

    def save_portfolio(self, portfolio: Portfolio) -> None:
        self.db.upsert_portfolio(portfolio.to_dict())

    def show_portfolio(self, user_id: int, base: str = "USD") -> dict:
        validate_currency_code(base)
        get_currency(base)  # проверка реестра

        portfolio = self.load_portfolio(user_id)
        wallets = portfolio.wallets
        if not wallets:
            return {"empty": True, "base": base, "rows": [], "total": 0.0}

        rows = []
        total = 0.0
        for code, w in sorted(wallets.items()):
            value = self._convert_amount(w.balance, code, base)
            rows.append({"code": code, "balance": w.balance, "value": value})
            total += value

        return {"empty": False, "base": base, "rows": rows, "total": total}

    # -------- rates --------
    def _get_pair_rate(self, from_code: str, to_code: str) -> tuple[float, str]:
        validate_currency_code(from_code)
        validate_currency_code(to_code)
        # Валидация через реестр
        get_currency(from_code)
        get_currency(to_code)

        snapshot = self._cached_rates()
        pairs = snapshot.get("pairs", {})
        key = pair_key(from_code, to_code)

        # в кеше хранятся в основном *_USD, поэтому поддерживаем расчёт через USD-мост
        if key in pairs:
            item = pairs[key]
            return float(item["rate"]), str(item["updated_at"])

        # if reverse exists
        rev = pair_key(to_code, from_code)
        if rev in pairs:
            item = pairs[rev]
            r = float(item["rate"])
            if r == 0:
                raise ApiRequestError("Нулевой курс в кеше")
            return 1.0 / r, str(item["updated_at"])

        # Cross через USD: from->USD и to->USD
        if from_code != "USD" and to_code != "USD":
            r_from, upd = self._get_pair_rate(from_code, "USD")
            r_to, _ = self._get_pair_rate(to_code, "USD")
            if r_to == 0:
                raise ApiRequestError("Нулевой курс USD-моста")
            return r_from / r_to, upd

        raise ApiRequestError(f"Курс {from_code}→{to_code} не найден в кеше")

    def get_rate(self, from_code: str, to_code: str) -> dict:
        try:
            rate, updated_at = self._get_pair_rate(from_code, to_code)
        except CurrencyNotFoundError:
            raise
        except ApiRequestError:
            # Если нет или устарело — пробуем обновить через Parser Service
            self._try_refresh_rates()
            rate, updated_at = self._get_pair_rate(from_code, to_code)

        ttl = int(self.settings.get("rates_ttl_seconds", 300))
        stale = False
        try:
            age = (datetime.now(UTC) - parse_dt(updated_at)).total_seconds()
            stale = age > ttl
        except Exception:  # noqa: BLE001
            stale = True

        return {"from": from_code, "to": to_code, "rate": rate, "updated_at": updated_at, "stale": stale}

    def _try_refresh_rates(self) -> None:
        try:
            from valutatrade_hub.parser_service.api_clients import (
                CoinGeckoClient,
                ExchangeRateApiClient,
            )
            from valutatrade_hub.parser_service.config import ParserConfig
            from valutatrade_hub.parser_service.storage import RatesStorage
            from valutatrade_hub.parser_service.updater import RatesUpdater

            cfg = ParserConfig()
            storage = RatesStorage(cfg)
            updater = RatesUpdater(
                clients=[CoinGeckoClient(cfg), ExchangeRateApiClient(cfg)],
                storage=storage,
            )
            updater.run_update()
            self._cached_rates = self._build_rates_reader(int(self.settings.get("rates_ttl_seconds", 300)))
        except Exception as e:  # noqa: BLE001
            raise ApiRequestError(str(e)) from e

    def _convert_amount(self, amount: float, from_code: str, to_code: str) -> float:
        if from_code.upper() == to_code.upper():
            return float(amount)
        r, _ = self._get_pair_rate(from_code, to_code)
        return float(amount) * r

    # -------- trading --------
    @log_action("BUY", verbose=True)
    def buy(self, user_id: int, currency_code: str, amount: float, base: str = "USD") -> dict:
        validate_currency_code(currency_code)
        ensure_float_positive(amount, "amount")
        get_currency(currency_code)

        portfolio = self.load_portfolio(user_id)
        code = currency_code.upper()
        base = base.upper()

        # гарантируем USD кошелёк
        usd = portfolio.get_wallet("USD") or portfolio.add_currency("USD")

        if code == "USD":
            before = usd.balance
            usd.deposit(amount)
            self.save_portfolio(portfolio)
            return {
                "user_id": user_id,
                "currency_code": "USD",
                "amount": amount,
                "rate": 1.0,
                "base": "USD",
                "before_after": f"USD: {before:.4f}→{usd.balance:.4f}",
            }

        # курс code->USD (стоимость покупки)
        rate, _ = self._get_pair_rate(code, "USD")
        cost_usd = amount * rate

        before_usd = usd.balance
        usd.withdraw(cost_usd)

        w = portfolio.get_wallet(code) or portfolio.add_currency(code)
        before_cur = w.balance
        w.deposit(amount)

        self.save_portfolio(portfolio)
        return {
            "user_id": user_id,
            "currency_code": code,
            "amount": amount,
            "rate": rate,
            "base": "USD",
            "before_after": f"USD: {before_usd:.4f}→{usd.balance:.4f}; {code}: {before_cur:.4f}→{w.balance:.4f}",
            "cost_usd": cost_usd,
        }

    @log_action("SELL", verbose=True)
    def sell(self, user_id: int, currency_code: str, amount: float, base: str = "USD") -> dict:
        validate_currency_code(currency_code)
        ensure_float_positive(amount, "amount")
        get_currency(currency_code)

        portfolio = self.load_portfolio(user_id)
        code = currency_code.upper()

        w = portfolio.get_wallet(code)
        if w is None:
            raise ValueError(
                f"У вас нет кошелька '{code}'. Добавьте валюту: она создаётся автоматически при первой покупке."
            )

        usd = portfolio.get_wallet("USD") or portfolio.add_currency("USD")

        if code == "USD":
            before = usd.balance
            usd.withdraw(amount)
            self.save_portfolio(portfolio)
            return {
                "user_id": user_id,
                "currency_code": "USD",
                "amount": amount,
                "rate": 1.0,
                "base": "USD",
                "before_after": f"USD: {before:.4f}→{usd.balance:.4f}",
                "proceeds_usd": amount,
            }

        rate, _ = self._get_pair_rate(code, "USD")
        proceeds = amount * rate

        before_cur = w.balance
        w.withdraw(amount)

        before_usd = usd.balance
        usd.deposit(proceeds)

        self.save_portfolio(portfolio)
        return {
            "user_id": user_id,
            "currency_code": code,
            "amount": amount,
            "rate": rate,
            "base": "USD",
            "before_after": f"{code}: {before_cur:.4f}→{w.balance:.4f}; USD: {before_usd:.4f}→{usd.balance:.4f}",
            "proceeds_usd": proceeds,
        }

    # -------- helpers for CLI --------
    def list_supported_codes(self) -> list[str]:
        return supported_codes()
