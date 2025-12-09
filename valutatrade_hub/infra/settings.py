from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib  # py311+
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


class SettingsLoader:
    _instance: SettingsLoader | None = None
    _loaded: bool = False

    def __new__(cls) -> SettingsLoader:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self.__class__._loaded:
            return
        self._config: dict[str, Any] = {}
        self.reload()
        self.__class__._loaded = True

    def reload(self) -> None:
        cfg: dict[str, Any] = {}
        pyproject = Path("pyproject.toml")
        if pyproject.exists() and tomllib is not None:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            cfg = ((data.get("tool") or {}).get("valutatrade") or {})
        self._config = dict(cfg)

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)
