"""Base de données SQLite pour stocker les données solaires.

Stratégie de rétention :
- Brut (1 min)      → conservé 7 jours      (~2 MB)
- Agrégé 15 min     → conservé 90 jours     (~6 MB)
- Agrégé horaire    → conservé 2 ans        (~3 MB)
- Résumé journalier → conservé indéfiniment (~0.1 MB/an)

Total estimé : ~12 MB/an au lieu de ~150 MB/an en brut.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pcq.config import RetentionConfig


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
                -- Données brutes (1 min), purgées après 7 jours
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

                -- Données agrégées 15 min, purgées après 90 jours
                CREATE TABLE IF NOT EXISTS production_quarter_hour (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT UNIQUE NOT NULL,
                    power_kw_avg REAL,
                    power_kw_min REAL,
                    power_kw_max REAL,
                    pv_input_power_kw_avg REAL,
                    efficiency_avg REAL,
                    inverter_temp_avg REAL,
                    sample_count INTEGER
                );

                CREATE TABLE IF NOT EXISTS grid_quarter_hour (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT UNIQUE NOT NULL,
                    export_power_w_avg REAL,
                    import_power_w_avg REAL,
                    voltage_avg REAL,
                    frequency_avg REAL,
                    sample_count INTEGER
                );

                -- Données agrégées horaires, purgées après 2 ans
                CREATE TABLE IF NOT EXISTS production_hourly (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT UNIQUE NOT NULL,
                    power_kw_avg REAL,
                    power_kw_min REAL,
                    power_kw_max REAL,
                    pv_input_power_kw_avg REAL,
                    efficiency_avg REAL,
                    inverter_temp_avg REAL,
                    sample_count INTEGER
                );

                CREATE TABLE IF NOT EXISTS grid_hourly (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT UNIQUE NOT NULL,
                    export_power_w_avg REAL,
                    import_power_w_avg REAL,
                    voltage_avg REAL,
                    frequency_avg REAL,
                    sample_count INTEGER
                );

                -- Résumés journaliers, conservés indéfiniment
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
                    savings_self_consumption REAL,
                    power_kw_peak REAL,
                    avg_efficiency REAL,
                    hours_of_production REAL
                );

                -- Résumés mensuels, conservés indéfiniment
                CREATE TABLE IF NOT EXISTS monthly_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    month TEXT UNIQUE NOT NULL,
                    total_production_kwh REAL,
                    total_consumption_kwh REAL,
                    self_consumed_kwh REAL,
                    exported_kwh REAL,
                    imported_kwh REAL,
                    self_consumption_rate REAL,
                    revenue_injection REAL,
                    savings_self_consumption REAL,
                    power_kw_peak REAL,
                    days_with_data INTEGER
                );

                -- Historique des tarifs
                CREATE TABLE IF NOT EXISTS tariff_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    quarter INTEGER,
                    buy_price_peak REAL,
                    buy_price_offpeak REAL,
                    feed_in_tariff REAL,
                    feed_in_q1 REAL,
                    feed_in_q2 REAL,
                    feed_in_q3 REAL,
                    feed_in_q4 REAL,
                    source TEXT,
                    UNIQUE(year, quarter)
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

                -- Journal de maintenance
                CREATE TABLE IF NOT EXISTS maintenance_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    rows_affected INTEGER,
                    details TEXT
                );

                -- Index
                CREATE INDEX IF NOT EXISTS idx_production_ts
                    ON production(timestamp);
                CREATE INDEX IF NOT EXISTS idx_grid_ts
                    ON grid(timestamp);
                CREATE INDEX IF NOT EXISTS idx_consumption_ts
                    ON consumption(timestamp);
                CREATE INDEX IF NOT EXISTS idx_prod_qh_ts
                    ON production_quarter_hour(timestamp);
                CREATE INDEX IF NOT EXISTS idx_grid_qh_ts
                    ON grid_quarter_hour(timestamp);
                CREATE INDEX IF NOT EXISTS idx_prod_hourly_ts
                    ON production_hourly(timestamp);
                CREATE INDEX IF NOT EXISTS idx_grid_hourly_ts
                    ON grid_hourly(timestamp);
                CREATE INDEX IF NOT EXISTS idx_daily_date
                    ON daily_summary(date);
                CREATE INDEX IF NOT EXISTS idx_monthly_month
                    ON monthly_summary(month);
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

    # --- Insertion données brutes ---

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
                    savings_self_consumption, power_kw_peak,
                    avg_efficiency, hours_of_production)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    data.get("power_kw_peak"),
                    data.get("avg_efficiency"),
                    data.get("hours_of_production"),
                ),
            )

    def insert_tariff_snapshot(self, tariff_config, source: str = "auto"):
        """Enregistre un snapshot des tarifs actuels."""
        now = datetime.now()
        quarter = (now.month - 1) // 3 + 1
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tariff_history
                   (timestamp, year, quarter, buy_price_peak, buy_price_offpeak,
                    feed_in_tariff, feed_in_q1, feed_in_q2, feed_in_q3, feed_in_q4, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now.isoformat(),
                    now.year,
                    quarter,
                    tariff_config.buy_price_peak,
                    tariff_config.buy_price_offpeak,
                    tariff_config.feed_in_tariff,
                    tariff_config.feed_in_q1,
                    tariff_config.feed_in_q2,
                    tariff_config.feed_in_q3,
                    tariff_config.feed_in_q4,
                    source,
                ),
            )

    def get_tariff_history(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tariff_history ORDER BY year, quarter"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Lecture ---

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

    def get_monthly_summaries(self, start: str, end: str) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM monthly_summary WHERE month BETWEEN ? AND ? ORDER BY month",
                (start, end),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_latest_production(self) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM production ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def get_production_adaptive(self, start: str, end: str) -> list:
        """Lecture adaptative : choisit la meilleure granularité selon la plage.

        - < 2 jours  → données brutes (1 min)
        - < 90 jours → données 15 min
        - < 2 ans    → données horaires
        - > 2 ans    → résumés journaliers
        """
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
        except ValueError:
            start_dt = datetime.strptime(start, "%Y-%m-%d")
            end_dt = datetime.strptime(end, "%Y-%m-%d")

        span_days = (end_dt - start_dt).days

        with self._connect() as conn:
            if span_days <= 2:
                table = "production"
                cols = "timestamp, power_kw as power_kw_avg, power_kw as power_kw_min, power_kw as power_kw_max"
            elif span_days <= 90:
                table = "production_quarter_hour"
                cols = "timestamp, power_kw_avg, power_kw_min, power_kw_max"
            elif span_days <= 730:
                table = "production_hourly"
                cols = "timestamp, power_kw_avg, power_kw_min, power_kw_max"
            else:
                rows = conn.execute(
                    "SELECT date as timestamp, total_production_kwh / COALESCE(hours_of_production, 10) as power_kw_avg "
                    "FROM daily_summary WHERE date BETWEEN ? AND ? ORDER BY date",
                    (start, end),
                ).fetchall()
                return [dict(r) for r in rows]

            rows = conn.execute(
                f"SELECT {cols} FROM {table} WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
                (start, end),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Agrégation et rétention ---

    def aggregate_to_quarter_hour(self, before: str):
        """Agrège les données brutes en intervalles de 15 min."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO production_quarter_hour
                    (timestamp, power_kw_avg, power_kw_min, power_kw_max,
                     pv_input_power_kw_avg, efficiency_avg, inverter_temp_avg, sample_count)
                SELECT
                    strftime('%%Y-%%m-%%dT%%H:', timestamp) ||
                        CASE
                            WHEN CAST(strftime('%%M', timestamp) AS INTEGER) < 15 THEN '00:00'
                            WHEN CAST(strftime('%%M', timestamp) AS INTEGER) < 30 THEN '15:00'
                            WHEN CAST(strftime('%%M', timestamp) AS INTEGER) < 45 THEN '30:00'
                            ELSE '45:00'
                        END as ts,
                    AVG(power_kw),
                    MIN(power_kw),
                    MAX(power_kw),
                    AVG(pv_input_power_kw),
                    AVG(efficiency),
                    AVG(inverter_temp),
                    COUNT(*)
                FROM production
                WHERE timestamp < ?
                GROUP BY ts
            """, (before,))

            conn.execute("""
                INSERT OR IGNORE INTO grid_quarter_hour
                    (timestamp, export_power_w_avg, import_power_w_avg,
                     voltage_avg, frequency_avg, sample_count)
                SELECT
                    strftime('%%Y-%%m-%%dT%%H:', timestamp) ||
                        CASE
                            WHEN CAST(strftime('%%M', timestamp) AS INTEGER) < 15 THEN '00:00'
                            WHEN CAST(strftime('%%M', timestamp) AS INTEGER) < 30 THEN '15:00'
                            WHEN CAST(strftime('%%M', timestamp) AS INTEGER) < 45 THEN '30:00'
                            ELSE '45:00'
                        END as ts,
                    AVG(export_power_w),
                    AVG(import_power_w),
                    AVG(voltage),
                    AVG(frequency),
                    COUNT(*)
                FROM grid
                WHERE timestamp < ?
                GROUP BY ts
            """, (before,))

    def aggregate_to_hourly(self, before: str):
        """Agrège les données 15 min en intervalles horaires."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO production_hourly
                    (timestamp, power_kw_avg, power_kw_min, power_kw_max,
                     pv_input_power_kw_avg, efficiency_avg, inverter_temp_avg, sample_count)
                SELECT
                    strftime('%%Y-%%m-%%dT%%H:00:00', timestamp) as ts,
                    AVG(power_kw_avg),
                    MIN(power_kw_min),
                    MAX(power_kw_max),
                    AVG(pv_input_power_kw_avg),
                    AVG(efficiency_avg),
                    AVG(inverter_temp_avg),
                    SUM(sample_count)
                FROM production_quarter_hour
                WHERE timestamp < ?
                GROUP BY ts
            """, (before,))

            conn.execute("""
                INSERT OR IGNORE INTO grid_hourly
                    (timestamp, export_power_w_avg, import_power_w_avg,
                     voltage_avg, frequency_avg, sample_count)
                SELECT
                    strftime('%%Y-%%m-%%dT%%H:00:00', timestamp) as ts,
                    AVG(export_power_w_avg),
                    AVG(import_power_w_avg),
                    AVG(voltage_avg),
                    AVG(frequency_avg),
                    SUM(sample_count)
                FROM grid_quarter_hour
                WHERE timestamp < ?
                GROUP BY ts
            """, (before,))

    def aggregate_daily_summary(self, date_str: str):
        """Calcule le résumé journalier depuis les données brutes ou 15 min."""
        with self._connect() as conn:
            next_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

            # Essayer d'abord les données brutes, sinon les 15 min
            row = conn.execute("""
                SELECT
                    AVG(power_kw) * COUNT(*) / 60.0 as total_production_kwh,
                    MAX(power_kw) as power_kw_peak,
                    AVG(efficiency) as avg_efficiency,
                    SUM(CASE WHEN power_kw > 0.1 THEN 1.0/60 ELSE 0 END) as hours_of_production
                FROM production
                WHERE timestamp >= ? AND timestamp < ?
            """, (date_str, next_date)).fetchone()

            if row and row["total_production_kwh"]:
                prod_kwh = row["total_production_kwh"]
                peak = row["power_kw_peak"]
                eff = row["avg_efficiency"]
                hours = row["hours_of_production"]
            else:
                row = conn.execute("""
                    SELECT
                        AVG(power_kw_avg) * COUNT(*) / 4.0 as total_production_kwh,
                        MAX(power_kw_max) as power_kw_peak,
                        AVG(efficiency_avg) as avg_efficiency,
                        SUM(CASE WHEN power_kw_avg > 0.1 THEN 0.25 ELSE 0 END) as hours_of_production
                    FROM production_quarter_hour
                    WHERE timestamp >= ? AND timestamp < ?
                """, (date_str, next_date)).fetchone()
                prod_kwh = row["total_production_kwh"] if row else 0
                peak = row["power_kw_peak"] if row else 0
                eff = row["avg_efficiency"] if row else 0
                hours = row["hours_of_production"] if row else 0

            # Données réseau
            grid_row = conn.execute("""
                SELECT
                    AVG(export_power_w) / 1000.0 * COUNT(*) / 60.0 as exported_kwh,
                    AVG(import_power_w) / 1000.0 * COUNT(*) / 60.0 as imported_kwh
                FROM grid
                WHERE timestamp >= ? AND timestamp < ?
            """, (date_str, next_date)).fetchone()

            exported = grid_row["exported_kwh"] if grid_row and grid_row["exported_kwh"] else 0
            imported = grid_row["imported_kwh"] if grid_row and grid_row["imported_kwh"] else 0

            prod_kwh = prod_kwh or 0
            self_consumed = max(0, prod_kwh - exported)
            total_conso = self_consumed + imported

            self.insert_daily_summary({
                "date": date_str,
                "total_production_kwh": round(prod_kwh, 2),
                "total_consumption_kwh": round(total_conso, 2),
                "self_consumed_kwh": round(self_consumed, 2),
                "exported_kwh": round(exported, 2),
                "imported_kwh": round(imported, 2),
                "self_consumption_rate": round(self_consumed / max(prod_kwh, 0.01) * 100, 1),
                "revenue_injection": None,
                "savings_self_consumption": None,
                "power_kw_peak": round(peak or 0, 2),
                "avg_efficiency": round(eff or 0, 1),
                "hours_of_production": round(hours or 0, 1),
            })

    def aggregate_monthly_summary(self, month_str: str):
        """Calcule le résumé mensuel depuis les résumés journaliers."""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    SUM(total_production_kwh) as total_production_kwh,
                    SUM(total_consumption_kwh) as total_consumption_kwh,
                    SUM(self_consumed_kwh) as self_consumed_kwh,
                    SUM(exported_kwh) as exported_kwh,
                    SUM(imported_kwh) as imported_kwh,
                    AVG(self_consumption_rate) as self_consumption_rate,
                    SUM(revenue_injection) as revenue_injection,
                    SUM(savings_self_consumption) as savings_self_consumption,
                    MAX(power_kw_peak) as power_kw_peak,
                    COUNT(*) as days_with_data
                FROM daily_summary
                WHERE date LIKE ? || '%'
            """, (month_str,)).fetchone()

            if row and row["total_production_kwh"]:
                conn.execute("""
                    INSERT OR REPLACE INTO monthly_summary
                        (month, total_production_kwh, total_consumption_kwh,
                         self_consumed_kwh, exported_kwh, imported_kwh,
                         self_consumption_rate, revenue_injection,
                         savings_self_consumption, power_kw_peak, days_with_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    month_str,
                    row["total_production_kwh"],
                    row["total_consumption_kwh"],
                    row["self_consumed_kwh"],
                    row["exported_kwh"],
                    row["imported_kwh"],
                    row["self_consumption_rate"],
                    row["revenue_injection"],
                    row["savings_self_consumption"],
                    row["power_kw_peak"],
                    row["days_with_data"],
                ))

    def purge_old_data(self, retention: RetentionConfig) -> dict:
        """Purge les données selon la politique de rétention."""
        now = datetime.now()
        stats = {}

        with self._connect() as conn:
            # Purger les données brutes (> raw_retention_days)
            cutoff_raw = (now - timedelta(days=retention.raw_retention_days)).isoformat()
            for table in ["production", "grid", "consumption"]:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE timestamp < ?", (cutoff_raw,)
                )
                stats[f"{table}_raw_deleted"] = cursor.rowcount

            # Purger les données 15 min (> quarter_hour_retention_days)
            cutoff_qh = (now - timedelta(days=retention.quarter_hour_retention_days)).isoformat()
            for table in ["production_quarter_hour", "grid_quarter_hour"]:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE timestamp < ?", (cutoff_qh,)
                )
                stats[f"{table}_deleted"] = cursor.rowcount

            # Purger les données horaires (> hourly_retention_days)
            cutoff_h = (now - timedelta(days=retention.hourly_retention_days)).isoformat()
            for table in ["production_hourly", "grid_hourly"]:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE timestamp < ?", (cutoff_h,)
                )
                stats[f"{table}_deleted"] = cursor.rowcount

            # Purger les anciennes prévisions météo (> 7 jours)
            cutoff_weather = (now - timedelta(days=7)).isoformat()
            cursor = conn.execute(
                "DELETE FROM weather_forecast WHERE timestamp < ?", (cutoff_weather,)
            )
            stats["weather_deleted"] = cursor.rowcount

        return stats

    def run_maintenance(self, retention: RetentionConfig) -> dict:
        """Maintenance complète : agrégation + purge + VACUUM.

        À appeler quotidiennement (ex: 02h00 du matin).
        """
        now = datetime.now()
        stats = {"timestamp": now.isoformat()}

        # 1. Agréger les données brutes > raw_retention_days en 15 min
        cutoff_raw = (now - timedelta(days=retention.raw_retention_days)).isoformat()
        self.aggregate_to_quarter_hour(cutoff_raw)
        stats["aggregated_to_15min_before"] = cutoff_raw

        # 2. Agréger les données 15 min > quarter_hour_retention_days en horaire
        cutoff_qh = (now - timedelta(days=retention.quarter_hour_retention_days)).isoformat()
        self.aggregate_to_hourly(cutoff_qh)
        stats["aggregated_to_hourly_before"] = cutoff_qh

        # 3. Générer les résumés journaliers (7 derniers jours)
        for i in range(1, 8):
            date_str = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            self.aggregate_daily_summary(date_str)
        stats["daily_summaries_updated"] = 7

        # 4. Générer le résumé mensuel du mois précédent
        prev_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        self.aggregate_monthly_summary(prev_month)
        stats["monthly_summary_updated"] = prev_month

        # 5. Purger les vieilles données
        purge_stats = self.purge_old_data(retention)
        stats.update(purge_stats)

        # 6. VACUUM pour récupérer l'espace disque
        conn = sqlite3.connect(self.db_path)
        conn.execute("VACUUM")
        conn.close()
        stats["vacuum"] = True

        # 7. Logger la maintenance
        with self._connect() as conn:
            total_deleted = sum(v for k, v in stats.items() if isinstance(v, int) and k.endswith("_deleted"))
            conn.execute(
                "INSERT INTO maintenance_log (timestamp, action, rows_affected, details) VALUES (?, ?, ?, ?)",
                (now.isoformat(), "daily_maintenance", total_deleted, str(stats)),
            )

        return stats

    def get_db_stats(self) -> dict:
        """Retourne les statistiques de la base de données."""
        stats = {}
        with self._connect() as conn:
            for table in [
                "production", "grid", "consumption",
                "production_quarter_hour", "grid_quarter_hour",
                "production_hourly", "grid_hourly",
                "daily_summary", "monthly_summary",
                "tariff_history", "weather_forecast", "maintenance_log",
            ]:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                stats[table] = row["cnt"]

        db_file = Path(self.db_path)
        if db_file.exists():
            stats["file_size_mb"] = round(db_file.stat().st_size / (1024 * 1024), 2)

        return stats
