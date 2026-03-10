"""Configuration de l'installation photovoltaïque - Cudrefin, Suisse."""

import os
from dataclasses import dataclass, field


@dataclass
class InstallationConfig:
    """Configuration de l'installation PV."""
    # Puissance crête installée en kWc
    peak_power_kwc: float = 19.0
    # Orientation des panneaux (azimut en degrés, 180 = Sud)
    azimuth: float = 180.0
    # Inclinaison des panneaux en degrés
    tilt: float = 30.0
    # Latitude / Longitude du site (Cudrefin, Suisse)
    latitude: float = 46.9553
    longitude: float = 7.0225
    # Rendement estimé du système (pertes câbles, température, etc.)
    system_efficiency: float = 0.85
    # Lieu
    location: str = "Cudrefin, Suisse"


@dataclass
class HuaweiConfig:
    """Configuration de connexion à l'API Huawei FusionSolar."""
    # URL de base de l'API FusionSolar
    base_url: str = "https://intl.fusionsolar.huawei.com/thirdData"
    # Identifiants - à remplir via variables d'environnement
    username: str = ""
    password: str = ""
    # ID de la station (plant)
    station_code: str = ""
    # Intervalle de collecte en minutes
    collection_interval_minutes: int = 5

    def __post_init__(self):
        self.username = os.environ.get("HUAWEI_FUSIONSOLAR_USER", self.username)
        self.password = os.environ.get("HUAWEI_FUSIONSOLAR_PASS", self.password)
        self.station_code = os.environ.get("HUAWEI_STATION_CODE", self.station_code)


@dataclass
class TariffConfig:
    """Tarifs Groupe E (Suisse) en CHF/kWh - 2026."""
    # Devise
    currency: str = "CHF"
    # Fournisseur
    provider: str = "Groupe E"
    # Tarif de reprise solaire (rachat injection)
    # Trimestriel basé sur le marché OFEN, min garanti 0.10 CHF/kWh avec GO (<30kW)
    # Fourchette: 0.086 - 0.138 CHF/kWh selon trimestre
    feed_in_tariff: float = 0.10
    # Prix d'achat électricité haut tarif HT (CHF/kWh) - tarif total 2026
    buy_price_peak: float = 0.2761
    # Prix d'achat électricité bas tarif BT (CHF/kWh) - tarif total 2026
    buy_price_offpeak: float = 0.2117
    # Heures en bas tarif 2026 Groupe E : 12h-17h et 23h-07h (tous les jours)
    offpeak_hours: list = field(default_factory=lambda: [(12, 17), (23, 7)])
    # Tarifs trimestriels de reprise (CHF/kWh, avec GO, estimations)
    feed_in_q1: float = 0.138  # Jan-Mar (hiver, GO 3ct)
    feed_in_q2: float = 0.086  # Avr-Jun (été, GO 1ct)
    feed_in_q3: float = 0.086  # Jul-Sep (été, GO 1ct)
    feed_in_q4: float = 0.138  # Oct-Déc (hiver, GO 3ct)


@dataclass
class RetentionConfig:
    """Politique de rétention et agrégation des données."""
    # Données brutes (1 min) : conservées X jours
    raw_retention_days: int = 7
    # Données 15 min : conservées X jours
    quarter_hour_retention_days: int = 90
    # Données horaires : conservées X jours
    hourly_retention_days: int = 730  # ~2 ans
    # Résumés journaliers : conservés indéfiniment
    # Heure de maintenance quotidienne (agrégation + purge)
    maintenance_hour: int = 2  # 02h00 du matin


@dataclass
class AppConfig:
    """Configuration globale de l'application."""
    installation: InstallationConfig = field(default_factory=InstallationConfig)
    huawei: HuaweiConfig = field(default_factory=HuaweiConfig)
    tariff: TariffConfig = field(default_factory=TariffConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    # Port du dashboard web
    dashboard_port: int = 8501
    # Chemin de la base de données SQLite
    db_path: str = "pcq/data/solar_data.db"
    # Intervalle d'actualisation du dashboard en secondes
    refresh_interval_seconds: int = 60
