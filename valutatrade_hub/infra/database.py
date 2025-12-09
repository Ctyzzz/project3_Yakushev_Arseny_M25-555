from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from valutatrade_hub.infra.settings import SettingsLoader


class DatabaseManager:
    _instance: DatabaseManager | None = None
    _loaded: bool = False

    def __new__(cls) -> DatabaseManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self.__class__._loaded:
            return
        self.settings = SettingsLoader()
        self.data_dir = Path(str(self.settings.get("data_dir", "data")))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.users_path = self.data_dir / "users.json"
        self.portfolios_path = self.data_dir / "portfolios.json"
        self.rates_path = self.data_dir / "rates.json"
        self.history_path = self.data_dir / "exchange_rates.json"
        self.session_path = self.data_dir / "session.json"

        self._ensure_files()
        self.__class__._loaded = True

    def _ensure_files(self) -> None:
        defaults: dict[Path, Any] = {
            self.users_path: [],
            self.portfolios_path: [],
            self.rates_path: {"pairs": {}, "last_refresh": None},
            self.history_path: [],
            self.session_path: {},
        }
        for p, default in defaults.items():
            if not p.exists():
                self.write_json_atomic(p, default)

    def read_json(self, path: Path) -> Any:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json_atomic(self, path: Path, obj: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    # --- users ---
    def list_users(self) -> list[dict[str, Any]]:
        return list(self.read_json(self.users_path) or [])

    def save_users(self, users: list[dict[str, Any]]) -> None:
        self.write_json_atomic(self.users_path, users)

    def next_user_id(self) -> int:
        users = self.list_users()
        if not users:
            return 1
        return max(int(u["user_id"]) for u in users) + 1

    def find_user_by_username(self, username: str) -> dict[str, Any] | None:
        uname = username.strip()
        for u in self.list_users():
            if u.get("username") == uname:
                return u
        return None

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        for u in self.list_users():
            if int(u.get("user_id", -1)) == int(user_id):
                return u
        return None

    def append_user(self, user: dict[str, Any]) -> None:
        users = self.list_users()
        users.append(user)
        self.save_users(users)

    # --- portfolios ---
    def list_portfolios(self) -> list[dict[str, Any]]:
        return list(self.read_json(self.portfolios_path) or [])

    def save_portfolios(self, portfolios: list[dict[str, Any]]) -> None:
        self.write_json_atomic(self.portfolios_path, portfolios)

    def get_portfolio(self, user_id: int) -> dict[str, Any] | None:
        for p in self.list_portfolios():
            if int(p.get("user_id", -1)) == int(user_id):
                return p
        return None

    def upsert_portfolio(self, portfolio: dict[str, Any]) -> None:
        portfolios = self.list_portfolios()
        uid = int(portfolio["user_id"])
        for i, p in enumerate(portfolios):
            if int(p.get("user_id", -1)) == uid:
                portfolios[i] = portfolio
                self.save_portfolios(portfolios)
                return
        portfolios.append(portfolio)
        self.save_portfolios(portfolios)

    # --- rates snapshot ---
    def read_rates(self) -> dict[str, Any]:
        data = self.read_json(self.rates_path) or {"pairs": {}, "last_refresh": None}
        if "pairs" not in data:
            data["pairs"] = {}
        return data

    def write_rates(self, data: dict[str, Any]) -> None:
        self.write_json_atomic(self.rates_path, data)

    # --- history ---
    def read_history(self) -> list[dict[str, Any]]:
        return list(self.read_json(self.history_path) or [])

    def append_history(self, entries: list[dict[str, Any]]) -> None:
        history = self.read_history()
        existing_ids = {e.get("id") for e in history}
        for e in entries:
            if e.get("id") not in existing_ids:
                history.append(e)
        self.write_json_atomic(self.history_path, history)

    # --- session ---
    def get_session(self) -> dict[str, Any]:
        return dict(self.read_json(self.session_path) or {})

    def set_session(self, session: dict[str, Any]) -> None:
        self.write_json_atomic(self.session_path, session)

    def clear_session(self) -> None:
        self.write_json_atomic(self.session_path, {})
