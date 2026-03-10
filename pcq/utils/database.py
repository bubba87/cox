"""Base de données SQLite pour stocker les données solaires."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional


class Database:
    """Gestionnaire de la base de données de monitoring solaire."""

    def __init__(self, db_path: str = "pcq/data/solar_data.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Crée les tables si elles n'existent pas."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS production (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    power_kw REAL,
                    daily_yield_kwh REAL,
                    total_yield_kwh REAL,
                    pv_input_power_kw REAL,
                    efficiency REAL,
                    inverter_temp REAL
                );

                CREATE TABLE IF NOT EXISTS grid (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    export_power_w REAL,
                    import_power_w REAL,
                    voltage REAL,
                    frequency REAL
                );

                CREATE TABLE IF NOT EXISTS consumption (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_consumption_kw REAL,
                    self_consumption_kw REAL,
                    grid_consumption_kw REAL
                );

                CREATE TABLE IF NOT EXISTS daily_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE NOT NULL,
                    total_production_kwh REAL,
                    total_consumption_kwh REAL,
                    self_consumed_kwh REAL,
                    exported_kwh REAL,
                    imported_kwh REAL,
                    self_consumption_rate REAL,
                    revenue_injection REAL,
                    savings_self_consumption REAL
                );

                CREATE TABLE IF NOT EXISTS weather_forecast (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    forecast_date TEXT NOT NULL,
                    cloud_cover REAL,
                    temperature REAL,
                    irradiance REAL,
                    predicted_production_kwh REAL
                );

                CREATE INDEX IF NOT EXISTS idx_production_ts
                    ON production(timestamp);
                CREATE INDEX IF NOT EXISTS idx_grid_ts
                    ON grid(timestamp);
                CREATE INDEX IF NOT EXISTS idx_consumption_ts
                    ON consumption(timestamp);
                CREATE INDEX IF NOT EXISTS idx_daily_date
                    ON daily_summary(date);
            """)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def insert_production(self, data: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO production
                   (timestamp, power_kw, daily_yield_kwh, total_yield_kwh,
                    pv_input_power_kw, efficiency, inverter_temp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("timestamp", datetime.now().isoformat()),
                    data.get("active_power"),
                    data.get("daily_yield"),
                    data.get("total_yield"),
                    data.get("input_power"),
                    data.get("efficiency"),
                    data.get("internal_temp"),
                ),
            )

    def insert_grid(self, data: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO grid
                   (timestamp, export_power_w, import_power_w, voltage, frequency)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    data.get("timestamp", datetime.now().isoformat()),
                    data.get("grid_export_power"),
                    data.get("grid_import_power"),
                    data.get("grid_voltage"),
                    data.get("grid_frequency"),
                ),
            )

    def insert_daily_summary(self, data: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO daily_summary
                   (date, total_production_kwh, total_consumption_kwh,
                    self_consumed_kwh, exported_kwh, imported_kwh,
                    self_consumption_rate, revenue_injection,
                    savings_self_consumption)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["date"],
                    data.get("total_production_kwh"),
                    data.get("total_consumption_kwh"),
                    data.get("self_consumed_kwh"),
                    data.get("exported_kwh"),
                    data.get("imported_kwh"),
                    data.get("self_consumption_rate"),
                    data.get("revenue_injection"),
                    data.get("savings_self_consumption"),
                ),
            )

    def get_production_range(self, start: str, end: str) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM production WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
                (start, end),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_daily_summaries(self, start: str, end: str) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_summary WHERE date BETWEEN ? AND ? ORDER BY date",
                (start, end),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_latest_production(self) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM production ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
