"""Configuration de l'installation photovoltaïque."""

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
    # Latitude / Longitude du site
    latitude: float = 48.8566
    longitude: float = 2.3522
    # Rendement estimé du système (pertes câbles, température, etc.)
    system_efficiency: float = 0.85


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
    """Tarifs EDF / grille tarifaire."""
    # Prix de rachat par EDF (€/kWh) - OA solaire
    feed_in_tariff: float = 0.1313
    # Prix d'achat électricité heures pleines (€/kWh)
    buy_price_peak: float = 0.2516
    # Prix d'achat électricité heures creuses (€/kWh)
    buy_price_offpeak: float = 0.1828
    # Heures creuses (plages horaires)
    offpeak_hours: list = field(default_factory=lambda: [(22, 6)])


@dataclass
class AppConfig:
    """Configuration globale de l'application."""
    installation: InstallationConfig = field(default_factory=InstallationConfig)
    huawei: HuaweiConfig = field(default_factory=HuaweiConfig)
    tariff: TariffConfig = field(default_factory=TariffConfig)
    # Port du dashboard web
    dashboard_port: int = 8501
    # Chemin de la base de données SQLite
    db_path: str = "pcq/data/solar_data.db"
