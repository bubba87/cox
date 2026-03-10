"""Optimiseur d'autoconsommation solaire.

Détermine les meilleurs moments pour utiliser l'électricité produite
plutôt que de la réinjecter dans le réseau.

Principes :
- Réinjecter = vendre à ~0.13€/kWh (tarif OA)
- Autoconsommer = économiser ~0.25€/kWh (prix achat HP)
- Donc autoconsommer est TOUJOURS plus rentable que réinjecter
- L'enjeu est de DÉCALER la consommation vers les heures de production
"""

from datetime import datetime, timedelta
from typing import Optional

from pcq.config import AppConfig, TariffConfig


class SelfConsumptionOptimizer:
    """Optimise l'autoconsommation en recommandant quand utiliser les appareils."""

    # Appareils typiques et leur consommation
    APPLIANCES = {
        "lave_linge": {"power_kw": 2.0, "duration_h": 1.5, "flexible": True},
        "seche_linge": {"power_kw": 2.5, "duration_h": 1.5, "flexible": True},
        "lave_vaisselle": {"power_kw": 1.8, "duration_h": 1.5, "flexible": True},
        "chauffe_eau": {"power_kw": 2.0, "duration_h": 3.0, "flexible": True},
        "voiture_electrique": {"power_kw": 7.4, "duration_h": 4.0, "flexible": True},
        "piscine_pompe": {"power_kw": 1.5, "duration_h": 6.0, "flexible": True},
        "climatisation": {"power_kw": 2.5, "duration_h": 4.0, "flexible": False},
        "four": {"power_kw": 2.5, "duration_h": 1.0, "flexible": False},
    }

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or AppConfig()
        self.tariff = self.config.tariff

    def is_offpeak(self, hour: int) -> bool:
        """Vérifie si l'heure est en heures creuses."""
        for start, end in self.tariff.offpeak_hours:
            if start > end:  # ex: 22h - 6h
                if hour >= start or hour < end:
                    return True
            elif start <= hour < end:
                return True
        return False

    def energy_cost(self, hour: int) -> float:
        """Prix de l'énergie achetée au réseau à une heure donnée (€/kWh)."""
        if self.is_offpeak(hour):
            return self.tariff.buy_price_offpeak
        return self.tariff.buy_price_peak

    def injection_revenue(self) -> float:
        """Revenu de la réinjection (€/kWh)."""
        return self.tariff.feed_in_tariff

    def savings_per_kwh(self, hour: int) -> float:
        """Économie nette par kWh autoconsommé vs réinjecté.

        = prix_achat_évité - prix_vente_perdu
        """
        return self.energy_cost(hour) - self.injection_revenue()

    def best_hours_for_appliance(
        self,
        appliance: str,
        production_forecast: list,
        base_consumption_kw: float = 1.0,
    ) -> dict:
        """Trouve le meilleur créneau pour faire tourner un appareil.

        Args:
            appliance: Nom de l'appareil (clé de APPLIANCES)
            production_forecast: Liste de dicts {time: "HH:MM", power_kw: float}
            base_consumption_kw: Consommation de base du foyer (hors appareil)

        Returns:
            Dict avec le créneau recommandé et les économies estimées
        """
        if appliance not in self.APPLIANCES:
            return {"error": f"Appareil inconnu: {appliance}"}

        app = self.APPLIANCES[appliance]
        power = app["power_kw"]
        duration_slots = int(app["duration_h"] * 4)  # slots de 15 min

        best_start = None
        best_savings = -999
        best_self_consumed = 0

        for i in range(len(production_forecast) - duration_slots):
            total_savings = 0
            total_self = 0

            for j in range(duration_slots):
                slot = production_forecast[i + j]
                hour = int(slot["time"].split(":")[0])
                available = max(0, slot["power_kw"] - base_consumption_kw)
                self_consumed = min(power, available)
                from_grid = power - self_consumed

                # Gain : énergie autoconsommée * (prix_achat - prix_vente)
                gain = self_consumed * self.savings_per_kwh(hour) * 0.25  # 15 min
                # Coût : énergie achetée au réseau
                cost = from_grid * self.energy_cost(hour) * 0.25
                total_savings += gain - cost
                total_self += self_consumed * 0.25

            if total_savings > best_savings:
                best_savings = total_savings
                best_start = i
                best_self_consumed = total_self

        if best_start is None:
            return {"recommendation": "Pas de créneau optimal trouvé"}

        start_time = production_forecast[best_start]["time"]
        end_idx = min(best_start + duration_slots, len(production_forecast) - 1)
        end_time = production_forecast[end_idx]["time"]

        return {
            "appliance": appliance,
            "recommended_start": start_time,
            "recommended_end": end_time,
            "estimated_self_consumed_kwh": round(best_self_consumed, 2),
            "estimated_savings_eur": round(best_savings, 3),
            "power_kw": power,
            "duration_h": app["duration_h"],
        }

    def daily_schedule(
        self,
        production_forecast: list,
        appliances: Optional[list] = None,
        base_consumption_kw: float = 1.0,
    ) -> dict:
        """Génère un planning journalier optimisé pour tous les appareils.

        Args:
            production_forecast: Prévision horaire [{time, power_kw}, ...]
            appliances: Liste d'appareils à planifier (None = tous les flexibles)
            base_consumption_kw: Consommation de base constante

        Returns:
            Planning optimisé avec recommandations
        """
        if appliances is None:
            appliances = [
                name for name, info in self.APPLIANCES.items() if info["flexible"]
            ]

        schedule = []
        remaining_production = [
            {**slot} for slot in production_forecast
        ]

        total_savings = 0

        for appliance in appliances:
            rec = self.best_hours_for_appliance(
                appliance, remaining_production, base_consumption_kw
            )
            if "error" not in rec and "recommended_start" in rec:
                schedule.append(rec)
                total_savings += rec.get("estimated_savings_eur", 0)

                # Réduire la production disponible pour les appareils suivants
                start_time = rec["recommended_start"]
                app_power = rec["power_kw"]
                started = False
                slots_consumed = 0
                duration_slots = int(
                    self.APPLIANCES[appliance]["duration_h"] * 4
                )
                for slot in remaining_production:
                    if slot["time"] == start_time:
                        started = True
                    if started and slots_consumed < duration_slots:
                        used = min(
                            app_power,
                            max(0, slot["power_kw"] - base_consumption_kw),
                        )
                        slot["power_kw"] -= used
                        slots_consumed += 1

        # Calculer le total de production et surplus
        total_production = sum(
            s["power_kw"] * 0.25 for s in production_forecast
        )
        total_self_consumed = sum(
            r.get("estimated_self_consumed_kwh", 0) for r in schedule
        )
        base_self = sum(
            min(s["power_kw"], base_consumption_kw) * 0.25
            for s in production_forecast
        )

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "schedule": schedule,
            "summary": {
                "total_production_kwh": round(total_production, 2),
                "base_self_consumption_kwh": round(base_self, 2),
                "appliances_self_consumption_kwh": round(total_self_consumed, 2),
                "estimated_surplus_kwh": round(
                    total_production - base_self - total_self_consumed, 2
                ),
                "total_estimated_savings_eur": round(total_savings, 3),
                "self_consumption_rate": round(
                    (base_self + total_self_consumed) / max(total_production, 0.01) * 100, 1
                ),
            },
        }

    def realtime_advice(
        self,
        current_production_kw: float,
        current_consumption_kw: float,
    ) -> dict:
        """Conseil temps réel basé sur la production et consommation actuelles.

        Returns:
            Dict avec le surplus actuel et des recommandations
        """
        surplus = current_production_kw - current_consumption_kw
        hour = datetime.now().hour

        advice = {
            "timestamp": datetime.now().isoformat(),
            "production_kw": current_production_kw,
            "consumption_kw": current_consumption_kw,
            "surplus_kw": round(surplus, 2),
            "status": "surplus" if surplus > 0 else "deficit",
            "recommendations": [],
        }

        if surplus > 0:
            advice["recommendations"].append(
                f"Surplus de {surplus:.1f} kW disponible - "
                "moment idéal pour lancer des appareils"
            )
            # Recommander les appareils qui rentrent dans le surplus
            for name, app in self.APPLIANCES.items():
                if app["flexible"] and app["power_kw"] <= surplus:
                    savings_h = self.savings_per_kwh(hour) * app["power_kw"]
                    advice["recommendations"].append(
                        f"  -> {name}: {app['power_kw']}kW pendant "
                        f"{app['duration_h']}h (économie ~{savings_h:.2f}€/h)"
                    )
        else:
            deficit = abs(surplus)
            cost_h = deficit * self.energy_cost(hour)
            advice["recommendations"].append(
                f"Déficit de {deficit:.1f} kW - vous achetez au réseau "
                f"(coût ~{cost_h:.2f}€/h)"
            )
            if not self.is_offpeak(hour):
                advice["recommendations"].append(
                    "Reportez les gros consommateurs aux heures de production solaire"
                )

        return advice
