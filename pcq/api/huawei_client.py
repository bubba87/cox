"""Client API Huawei FusionSolar pour collecte de données.

L'API FusionSolar (iMaster NetEco / thirdData) permet de récupérer
les données temps réel et historiques de l'onduleur Huawei.

Documentation officielle :
https://support.huawei.com/enterprise/en/doc/EDOC1100261860

Alternative locale : l'onduleur Huawei expose aussi une API Modbus TCP
sur le réseau local (port 502) pour une collecte sans cloud.
"""

import hashlib
import json
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from pcq.config import HuaweiConfig


class HuaweiFusionSolarClient:
    """Client pour l'API Huawei FusionSolar (Northbound Interface)."""

    def __init__(self, config: Optional[HuaweiConfig] = None):
        self.config = config or HuaweiConfig()
        self.session = requests.Session()
        self.token: Optional[str] = None
        self.token_expiry: float = 0

    def _login(self):
        """Authentification auprès de l'API FusionSolar."""
        url = f"{self.config.base_url}/login"
        payload = {
            "userName": self.config.username,
            "systemCode": self.config.password,
        }
        resp = self.session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success", False):
            raise ConnectionError(
                f"Échec de connexion FusionSolar: {data.get('failCode', 'inconnu')}"
            )

        self.token = resp.headers.get("xsrf-token")
        self.session.headers.update({"xsrf-token": self.token})
        # Token valide 30 minutes
        self.token_expiry = time.time() + 1700

    def _ensure_auth(self):
        """S'assure que le token est valide."""
        if not self.token or time.time() >= self.token_expiry:
            self._login()

    def _post(self, endpoint: str, payload: dict) -> dict:
        """Requête POST authentifiée."""
        self._ensure_auth()
        url = f"{self.config.base_url}/{endpoint}"
        resp = self.session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success", False):
            raise RuntimeError(f"Erreur API FusionSolar: {data}")
        return data.get("data", data)

    def get_station_list(self) -> list:
        """Liste des stations (installations) du compte."""
        return self._post("getStationList", {"pageNo": 1, "pageSize": 100})

    def get_station_realtime(self, station_code: Optional[str] = None) -> dict:
        """Données temps réel de la station."""
        code = station_code or self.config.station_code
        return self._post("getStationRealKpi", {"stationCodes": code})

    def get_station_daily(
        self,
        date: Optional[datetime] = None,
        station_code: Optional[str] = None,
    ) -> dict:
        """Données journalières de la station."""
        code = station_code or self.config.station_code
        dt = date or datetime.now()
        # FusionSolar attend un timestamp en millisecondes (début de journée)
        collect_time = int(
            datetime(dt.year, dt.month, dt.day).timestamp() * 1000
        )
        return self._post(
            "getKpiStationDay",
            {"stationCodes": code, "collectTime": collect_time},
        )

    def get_station_monthly(
        self,
        date: Optional[datetime] = None,
        station_code: Optional[str] = None,
    ) -> dict:
        """Données mensuelles de la station."""
        code = station_code or self.config.station_code
        dt = date or datetime.now()
        collect_time = int(
            datetime(dt.year, dt.month, 1).timestamp() * 1000
        )
        return self._post(
            "getKpiStationMonth",
            {"stationCodes": code, "collectTime": collect_time},
        )

    def get_device_list(self, station_code: Optional[str] = None) -> list:
        """Liste des équipements de la station (onduleurs, compteurs...)."""
        code = station_code or self.config.station_code
        return self._post("getDevList", {"stationCodes": code})

    def get_inverter_realtime(self, inverter_id: str) -> dict:
        """Données temps réel d'un onduleur spécifique."""
        return self._post(
            "getDevRealKpi",
            {"devIds": inverter_id, "devTypeId": 1},  # 1 = onduleur
        )

    def get_inverter_history(
        self,
        inverter_id: str,
        date: Optional[datetime] = None,
    ) -> dict:
        """Historique 5 minutes d'un onduleur pour une journée."""
        dt = date or datetime.now()
        collect_time = int(
            datetime(dt.year, dt.month, dt.day).timestamp() * 1000
        )
        return self._post(
            "getDevHistoryKpi",
            {
                "devIds": inverter_id,
                "devTypeId": 1,
                "startTime": collect_time,
                "endTime": collect_time + 86400000,  # +24h en ms
            },
        )

    def get_meter_realtime(self, meter_id: str) -> dict:
        """Données temps réel du compteur (consommation / injection)."""
        return self._post(
            "getDevRealKpi",
            {"devIds": meter_id, "devTypeId": 17},  # 17 = compteur
        )


class HuaweiModbusClient:
    """Client Modbus TCP pour collecte locale depuis l'onduleur Huawei.

    L'onduleur Huawei SUN2000 expose un serveur Modbus TCP sur le port 502.
    Cela permet la collecte de données sans dépendre du cloud FusionSolar.

    Nécessite: pip install pymodbus
    """

    # Registres Modbus importants du SUN2000
    REGISTERS = {
        "active_power": (32080, 2, 1000),       # Puissance active (kW)
        "daily_yield": (32114, 2, 100),          # Production journalière (kWh)
        "total_yield": (32106, 2, 100),          # Production totale (kWh)
        "grid_voltage": (32066, 1, 10),          # Tension réseau (V)
        "grid_frequency": (32085, 1, 100),       # Fréquence réseau (Hz)
        "efficiency": (32086, 1, 100),           # Rendement (%)
        "internal_temp": (32087, 1, 10),         # Température interne (°C)
        "pv1_voltage": (32016, 1, 10),           # Tension string PV1 (V)
        "pv1_current": (32017, 1, 100),          # Courant string PV1 (A)
        "pv2_voltage": (32018, 1, 10),           # Tension string PV2 (V)
        "pv2_current": (32019, 1, 100),          # Courant string PV2 (A)
        "input_power": (32064, 2, 1000),         # Puissance d'entrée PV (kW)
        "grid_export_power": (37113, 2, 1),      # Puissance exportée (W)
        "grid_import_power": (37119, 2, 1),      # Puissance importée (W)
    }

    def __init__(self, host: str = "192.168.200.1", port: int = 502, unit_id: int = 1):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self._client = None

    def connect(self):
        """Connexion Modbus TCP à l'onduleur."""
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError:
            raise ImportError(
                "pymodbus est requis pour la connexion locale. "
                "Installez-le avec: pip install pymodbus"
            )
        self._client = ModbusTcpClient(self.host, port=self.port)
        if not self._client.connect():
            raise ConnectionError(
                f"Impossible de se connecter à l'onduleur sur {self.host}:{self.port}"
            )

    def disconnect(self):
        if self._client:
            self._client.close()

    def read_register(self, name: str) -> float:
        """Lit un registre par nom et retourne la valeur convertie."""
        if name not in self.REGISTERS:
            raise ValueError(f"Registre inconnu: {name}")

        address, count, scale = self.REGISTERS[name]
        result = self._client.read_holding_registers(
            address, count, slave=self.unit_id
        )
        if result.isError():
            raise RuntimeError(f"Erreur lecture registre {name}: {result}")

        if count == 2:
            raw = (result.registers[0] << 16) | result.registers[1]
        else:
            raw = result.registers[0]

        return raw / scale

    def read_all(self) -> dict:
        """Lit tous les registres et retourne un dictionnaire."""
        data = {"timestamp": datetime.now().isoformat()}
        for name in self.REGISTERS:
            try:
                data[name] = self.read_register(name)
            except Exception as e:
                data[name] = None
        return data

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()
