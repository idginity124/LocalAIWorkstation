"""Allow-listed application settings with validation and SQLite persistence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "telemetry_refresh_seconds": 5,
}


def validate_setting(key: str, value: Any) -> Any:
    if key == "theme":
        if not isinstance(value, str) or value not in {"dark", "light", "system"}:
            raise ValueError("Tema dark, light veya system olmalı.")
        return value
    if key == "telemetry_refresh_seconds":
        if type(value) is not int or value not in {2, 5, 10}:
            raise ValueError("Telemetri yenileme aralığı 2, 5 veya 10 saniye olmalı.")
        return value
    raise KeyError("Bu ayar değiştirilemez veya bulunamadı.")


class SettingsService:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get_all(self) -> dict[str, Any]:
        stored = dict(DEFAULTS)
        for row in self.connection.execute('SELECT key,value_json FROM settings'):
            if row['key'] not in DEFAULTS:
                continue
            try:
                stored[row['key']] = validate_setting(row['key'], json.loads(row['value_json']))
            except (ValueError, TypeError, KeyError):
                continue
        return stored

    def update(self, key: str, value: Any) -> dict[str, Any]:
        clean_value = validate_setting(key, value)
        encoded = json.dumps(clean_value, ensure_ascii=False, separators=(",", ":"))
        with self._transaction():
            self.connection.execute(
                "INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=CURRENT_TIMESTAMP",
                (key, encoded),
            )
        return self.get_all()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.execute("COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise
