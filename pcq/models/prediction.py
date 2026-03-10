"""Modèle de prédiction de production solaire.

Utilise une combinaison de :
- Modèle astronomique (position du soleil, irradiance théorique)
- Données météo (couverture nuageuse via Open-Meteo API gratuite)
- Historique de production pour affiner les prédictions
"""

import math
from datetime import datetime, timedelta
from typing import Optional

import requests

from pcq.config import InstallationConfig


class ProductionPredictor:
    """Prédit la production solaire future."""

    # Constante solaire (W/m²)
    SOLAR_CONSTANT = 1361

    def __init__(self, config: Optional[InstallationConfig] = None):
        self.config = config or InstallationConfig()

    def solar_declination(self, day_of_year: int) -> float:
        """Déclinaison solaire en radians."""
        return math.radians(23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81))))

    def hour_angle(self, hour: float, longitude: float) -> float:
        """Angle horaire en radians (15° par heure, midi = 0)."""
        solar_noon_offset = longitude / 15
        return math.radians(15 * (hour - 12 + solar_noon_offset))

    def solar_elevation(self, dt: datetime) -> float:
        """Élévation solaire en degrés pour un instant donné."""
        lat_rad = math.radians(self.config.latitude)
        day = dt.timetuple().tm_yday
        decl = self.solar_declination(day)
        ha = self.hour_angle(dt.hour + dt.minute / 60, self.config.longitude)

        sin_elev = (
            math.sin(lat_rad) * math.sin(decl)
            + math.cos(lat_rad) * math.cos(decl) * math.cos(ha)
        )
        return math.degrees(math.asin(max(-1, min(1, sin_elev))))

    def clear_sky_irradiance(self, dt: datetime) -> float:
        """Irradiance par ciel clair sur les panneaux (W/m²)."""
        elevation = self.solar_elevation(dt)
        if elevation <= 0:
            return 0.0

        # Masse d'air (air mass)
        zenith = 90 - elevation
        if zenith >= 90:
            return 0.0
        air_mass = 1 / math.cos(math.radians(zenith))

        # Irradiance directe (modèle simplifié Hottel)
        dni = self.SOLAR_CONSTANT * 0.7 ** (air_mass ** 0.678)

        # Projection sur les panneaux inclinés
        tilt_rad = math.radians(self.config.tilt)
        elev_rad = math.radians(elevation)

        # Angle d'incidence simplifié (pour azimut sud)
        cos_incidence = (
            math.sin(elev_rad) * math.cos(tilt_rad)
            + math.cos(elev_rad) * math.sin(tilt_rad)
        )
        cos_incidence = max(0, cos_incidence)

        # Ajouter composante diffuse (~15% de la directe)
        diffuse = dni * 0.15
        return dni * cos_incidence + diffuse

    def estimate_power(self, dt: datetime, cloud_cover: float = 0.0) -> float:
        """Estime la puissance instantanée en kW.

        Args:
            dt: Instant de la prédiction
            cloud_cover: Couverture nuageuse entre 0.0 (clair) et 1.0 (couvert)

        Returns:
            Puissance estimée en kW
        """
        irradiance = self.clear_sky_irradiance(dt)
        if irradiance <= 0:
            return 0.0

        # Facteur d'atténuation par les nuages
        cloud_factor = 1.0 - (cloud_cover * 0.75)

        # Puissance = irradiance * surface * rendement
        # surface_effective ≈ peak_power / 1000 * 1kWc (environ 5-6 m²/kWc)
        # Simplifié : on rapporte à la puissance crête
        stc_irradiance = 1000  # W/m² conditions STC
        power_kw = (
            self.config.peak_power_kwc
            * (irradiance / stc_irradiance)
            * cloud_factor
            * self.config.system_efficiency
        )

        return min(power_kw, self.config.peak_power_kwc)

    def get_weather_forecast(self, days: int = 3) -> list:
        """Récupère les prévisions météo via Open-Meteo (API gratuite).

        Returns:
            Liste de dicts avec hourly cloud_cover, temperature, irradiance
        """
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": self.config.latitude,
            "longitude": self.config.longitude,
            "hourly": "cloud_cover,temperature_2m,direct_radiation",
            "forecast_days": days,
            "timezone": "auto",
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            forecasts = []
            for i, t in enumerate(times):
                forecasts.append({
                    "datetime": t,
                    "cloud_cover": hourly.get("cloud_cover", [0])[i] / 100.0,
                    "temperature": hourly.get("temperature_2m", [0])[i],
                    "irradiance": hourly.get("direct_radiation", [0])[i],
                })
            return forecasts
        except Exception:
            return []

    def predict_day(self, date: Optional[datetime] = None, weather: Optional[list] = None) -> dict:
        """Prédit la production pour une journée complète.

        Returns:
            Dict avec production horaire et totale estimée.
        """
        dt = date or datetime.now()
        target_date = dt.strftime("%Y-%m-%d")

        # Préparer les données météo par heure
        weather_by_hour = {}
        if weather:
            for w in weather:
                w_dt = w["datetime"]
                if isinstance(w_dt, str) and w_dt.startswith(target_date):
                    hour = int(w_dt[11:13])
                    weather_by_hour[hour] = w

        hourly = []
        total_kwh = 0.0

        for hour in range(24):
            for minute in [0, 15, 30, 45]:
                t = datetime(dt.year, dt.month, dt.day, hour, minute)
                cloud = weather_by_hour.get(hour, {}).get("cloud_cover", 0.2)
                power = self.estimate_power(t, cloud)
                total_kwh += power * 0.25  # 15 min = 0.25h
                hourly.append({
                    "time": t.strftime("%H:%M"),
                    "power_kw": round(power, 3),
                    "cloud_cover": cloud,
                })

        return {
            "date": target_date,
            "total_estimated_kwh": round(total_kwh, 2),
            "peak_power_kw": round(max(h["power_kw"] for h in hourly), 2),
            "sunrise_approx": next(
                (h["time"] for h in hourly if h["power_kw"] > 0.1), "N/A"
            ),
            "sunset_approx": next(
                (h["time"] for h in reversed(hourly) if h["power_kw"] > 0.1), "N/A"
            ),
            "hourly": hourly,
        }

    def predict_week(self) -> list:
        """Prédit la production pour les 7 prochains jours."""
        weather = self.get_weather_forecast(days=7)
        predictions = []
        for i in range(7):
            day = datetime.now() + timedelta(days=i)
            pred = self.predict_day(day, weather)
            predictions.append(pred)
        return predictions
