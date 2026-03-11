"""Collecteur de données solaires.

Lance la collecte périodique des données depuis l'onduleur Huawei.
Inclut la maintenance automatique (agrégation + purge) à 02h00.

Usage:
    # Via l'API cloud FusionSolar
    python -m pcq.collector --mode cloud

    # Via Modbus TCP local (recommandé)
    python -m pcq.collector --mode local --host 192.168.200.1

    # Mode démo (données simulées)
    python -m pcq.collector --mode demo
"""

import argparse
import math
import random
import time
from datetime import datetime
from pathlib import Path

from pcq.config import AppConfig
from pcq.api.huawei_client import HuaweiFusionSolarClient, HuaweiModbusClient
from pcq.api.tariff_updater import TariffUpdater
from pcq.utils.database import Database


def collect_cloud(config: AppConfig, db: Database):
    """Collecte via l'API cloud FusionSolar."""
    client = HuaweiFusionSolarClient(config.huawei)

    try:
        realtime = client.get_station_realtime()
        data_list = realtime if isinstance(realtime, list) else [realtime]

        for station_data in data_list:
            kpi = station_data.get("dataItemMap", station_data)
            db.insert_production({
                "timestamp": datetime.now().isoformat(),
                "active_power": kpi.get("real_health_state_power", kpi.get("day_power")),
                "daily_yield": kpi.get("day_power"),
                "total_yield": kpi.get("total_power"),
                "input_power": None,
                "efficiency": None,
                "internal_temp": None,
            })
            print(f"[{datetime.now():%H:%M:%S}] Cloud: {kpi.get('day_power', '?')} kWh aujourd'hui")

    except Exception as e:
        print(f"Erreur collecte cloud: {e}")


def collect_local(host: str, db: Database):
    """Collecte via Modbus TCP local."""
    client = HuaweiModbusClient(host=host)

    try:
        with client:
            data = client.read_all()
            db.insert_production(data)
            db.insert_grid(data)
            power = data.get("active_power", 0)
            daily = data.get("daily_yield", 0)
            print(f"[{datetime.now():%H:%M:%S}] Local: {power:.1f} kW | {daily:.1f} kWh jour")
    except ImportError:
        print("pymodbus non installé. Installez avec: pip install pymodbus")
    except Exception as e:
        print(f"Erreur collecte locale: {e}")


def collect_demo(db: Database, peak_kwc: float = 19.0):
    """Mode démo : génère des données simulées réalistes."""
    now = datetime.now()
    hour = now.hour + now.minute / 60

    if 6 <= hour <= 20:
        solar_factor = math.exp(-0.5 * ((hour - 13) / 3) ** 2)
        cloud_factor = 1.0 - random.uniform(0, 0.3)
        power = peak_kwc * solar_factor * cloud_factor * 0.85
        power = max(0, power + random.gauss(0, 0.5))
    else:
        power = 0

    daily_yield = power * (hour - 6) * 0.4 if hour > 6 else 0

    data = {
        "timestamp": now.isoformat(),
        "active_power": round(power, 2),
        "daily_yield": round(max(0, daily_yield), 2),
        "total_yield": round(25000 + daily_yield, 2),
        "input_power": round(power * 1.05, 2),
        "efficiency": round(min(98, 80 + power / peak_kwc * 18), 1) if power > 0 else 0,
        "internal_temp": round(25 + power * 1.5 + random.gauss(0, 2), 1),
        "grid_export_power": round(max(0, (power - 1.5) * 1000), 0),
        "grid_import_power": round(max(0, (1.5 - power) * 1000), 0),
        "grid_voltage": round(230 + random.gauss(0, 2), 1),
        "grid_frequency": round(50 + random.gauss(0, 0.02), 2),
    }

    db.insert_production(data)
    db.insert_grid(data)
    print(
        f"[{now:%H:%M:%S}] Demo: {power:.1f} kW | "
        f"{daily_yield:.1f} kWh jour | "
        f"Export: {data['grid_export_power']:.0f}W"
    )


def maybe_run_maintenance(config: AppConfig, db: Database, last_maintenance_date: str) -> str:
    """Exécute la maintenance quotidienne si l'heure est venue.

    Returns:
        La date de la dernière maintenance effectuée.
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if today == last_maintenance_date:
        return last_maintenance_date

    if now.hour == config.retention.maintenance_hour:
        print(f"\n[{now:%H:%M:%S}] Maintenance quotidienne en cours...")
        try:
            # Mise à jour des tarifs
            updater = TariffUpdater(str(Path(config.db_path).parent))
            changes = updater.update_tariffs(config.tariff)
            if changes:
                db.insert_tariff_snapshot(config.tariff, source="auto")
                print(f"[{now:%H:%M:%S}] Tarifs mis à jour: {changes}")
            else:
                print(f"[{now:%H:%M:%S}] Tarifs inchangés")

            # Maintenance DB (agrégation + purge)
            stats = db.run_maintenance(config.retention)
            total_deleted = sum(
                v for k, v in stats.items()
                if isinstance(v, int) and k.endswith("_deleted")
            )
            db_stats = db.get_db_stats()
            print(f"[{now:%H:%M:%S}] Maintenance terminée:")
            print(f"  - Lignes purgées: {total_deleted}")
            print(f"  - Taille DB: {db_stats.get('file_size_mb', '?')} MB")
            print(f"  - Brut: {db_stats.get('production', 0)} | "
                  f"15min: {db_stats.get('production_quarter_hour', 0)} | "
                  f"Horaire: {db_stats.get('production_hourly', 0)} | "
                  f"Jours: {db_stats.get('daily_summary', 0)}\n")
            return today
        except Exception as e:
            print(f"[{now:%H:%M:%S}] Erreur maintenance: {e}\n")

    return last_maintenance_date


def main():
    parser = argparse.ArgumentParser(description="Collecteur de données solaires PCQ")
    parser.add_argument(
        "--mode",
        choices=["cloud", "local", "demo"],
        default="demo",
        help="Mode de collecte (default: demo)",
    )
    parser.add_argument(
        "--host",
        default="192.168.200.1",
        help="IP de l'onduleur pour le mode local (default: 192.168.200.1)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Intervalle de collecte en secondes (default: 300 = 5 min)",
    )
    args = parser.parse_args()

    config = AppConfig()
    db = Database(config.db_path)
    last_maintenance = ""

    print(f"PCQ Collecteur - Mode: {args.mode} | Intervalle: {args.interval}s")
    print(f"Installation: {config.installation.peak_power_kwc} kWc | {config.installation.location}")
    print(f"Rétention: brut {config.retention.raw_retention_days}j | "
          f"15min {config.retention.quarter_hour_retention_days}j | "
          f"horaire {config.retention.hourly_retention_days}j")
    print(f"Maintenance auto: {config.retention.maintenance_hour:02d}h00")
    print("Ctrl+C pour arrêter\n")

    while True:
        try:
            if args.mode == "cloud":
                collect_cloud(config, db)
            elif args.mode == "local":
                collect_local(args.host, db)
            else:
                collect_demo(db, config.installation.peak_power_kwc)

            # Vérifier si maintenance nécessaire
            last_maintenance = maybe_run_maintenance(config, db, last_maintenance)

            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nArrêt du collecteur.")
            break


if __name__ == "__main__":
    main()
