"""Calcul d'amortissement de l'installation photovoltaïque.

Modèle financier sur 25 ans tenant compte de :
- Subventions (Pronovo, cantonales)
- Dégradation annuelle des panneaux (~0.5%/an)
- Remplacement onduleur (à 15 ans)
- Hausse du prix de l'électricité
- Tarifs trimestriels de reprise (Groupe E)
- Taux d'autoconsommation réel ou estimé
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pcq.config import AppConfig, InvestmentConfig, TariffConfig


@dataclass
class YearlyFinancials:
    """Résultat financier pour une année donnée."""
    year: int
    production_kwh: float
    self_consumed_kwh: float
    exported_kwh: float
    revenue_injection_chf: float
    savings_self_consumption_chf: float
    total_gain_chf: float
    maintenance_cost_chf: float
    exceptional_cost_chf: float
    net_gain_chf: float
    cumulative_gain_chf: float
    remaining_investment_chf: float
    roi_pct: float


class AmortizationCalculator:
    """Calcule l'amortissement et le retour sur investissement."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or AppConfig()
        self.investment = self.config.investment
        self.tariff = self.config.tariff
        self.installation = self.config.installation

    def annual_production_kwh(self, year_offset: int = 0) -> float:
        """Production annuelle estimée en kWh avec dégradation.

        Pour la Suisse (46°N), production typique ~950-1050 kWh/kWc/an.
        On utilise 980 kWh/kWc comme base pour Cudrefin.
        """
        base_kwh_per_kwc = 980  # kWh/kWc/an pour la Suisse romande
        base_production = self.installation.peak_power_kwc * base_kwh_per_kwc

        degradation = (1 - self.investment.annual_degradation_pct / 100) ** year_offset
        return base_production * degradation

    def annual_feed_in_revenue(self, exported_kwh: float) -> float:
        """Revenu annuel de la réinjection (moyenne pondérée trimestrielle).

        Distribution approximative de la production solaire par trimestre :
        Q1: 10%, Q2: 35%, Q3: 35%, Q4: 20%
        """
        seasonal_weights = {
            "q1": 0.10,
            "q2": 0.35,
            "q3": 0.35,
            "q4": 0.20,
        }
        weighted_tariff = (
            self.tariff.feed_in_q1 * seasonal_weights["q1"]
            + self.tariff.feed_in_q2 * seasonal_weights["q2"]
            + self.tariff.feed_in_q3 * seasonal_weights["q3"]
            + self.tariff.feed_in_q4 * seasonal_weights["q4"]
        )
        return exported_kwh * weighted_tariff

    def annual_self_consumption_savings(
        self, self_consumed_kwh: float, year_offset: int = 0
    ) -> float:
        """Économies annuelles grâce à l'autoconsommation.

        Tient compte de la hausse annuelle du prix de l'électricité.
        Pondération HT/BT selon la répartition solaire dans la journée :
        - Production solaire entre 7h-20h
        - Heures BT Groupe E : 12h-17h → ~38% de la production en BT
        """
        price_increase = (
            1 + self.investment.electricity_price_increase_pct / 100
        ) ** year_offset

        # Pondération HT/BT selon les heures de production
        bt_share = 0.38  # ~38% de la production tombe en heures BT (12h-17h)
        ht_share = 1 - bt_share

        weighted_price = (
            self.tariff.buy_price_peak * ht_share
            + self.tariff.buy_price_offpeak * bt_share
        ) * price_increase

        return self_consumed_kwh * weighted_price

    def calculate_yearly(
        self,
        year_offset: int,
        self_consumption_pct: Optional[float] = None,
        cumulative_gain_previous: float = 0,
    ) -> YearlyFinancials:
        """Calcule les finances pour une année donnée.

        Args:
            year_offset: Nombre d'années depuis la mise en service (0 = 1ère année)
            self_consumption_pct: Taux d'autoconsommation (si None, utilise la config)
            cumulative_gain_previous: Gain cumulé des années précédentes
        """
        sc_pct = self_consumption_pct or self.investment.estimated_self_consumption_pct

        production = self.annual_production_kwh(year_offset)
        self_consumed = production * sc_pct / 100
        exported = production - self_consumed

        revenue = self.annual_feed_in_revenue(exported)
        savings = self.annual_self_consumption_savings(self_consumed, year_offset)
        total_gain = revenue + savings

        maintenance = self.investment.annual_maintenance_cost

        # Remplacement onduleur à mi-vie
        exceptional = 0.0
        if year_offset == self.investment.inverter_lifespan_years:
            exceptional = self.investment.inverter_replacement_cost

        net_gain = total_gain - maintenance - exceptional
        cumulative = cumulative_gain_previous + net_gain

        net_cost = self.investment.net_cost
        remaining = net_cost - cumulative

        start_year = int(self.investment.commissioning_date[:4])

        return YearlyFinancials(
            year=start_year + year_offset,
            production_kwh=round(production, 0),
            self_consumed_kwh=round(self_consumed, 0),
            exported_kwh=round(exported, 0),
            revenue_injection_chf=round(revenue, 2),
            savings_self_consumption_chf=round(savings, 2),
            total_gain_chf=round(total_gain, 2),
            maintenance_cost_chf=round(maintenance, 2),
            exceptional_cost_chf=round(exceptional, 2),
            net_gain_chf=round(net_gain, 2),
            cumulative_gain_chf=round(cumulative, 2),
            remaining_investment_chf=round(remaining, 2),
            roi_pct=round(cumulative / max(net_cost, 1) * 100, 1),
        )

    def calculate_amortization(
        self, self_consumption_pct: Optional[float] = None
    ) -> dict:
        """Calcule l'amortissement complet sur la durée de vie.

        Returns:
            Dict avec le résumé et le détail année par année.
        """
        sc_pct = self_consumption_pct or self.investment.estimated_self_consumption_pct
        lifespan = self.investment.panel_lifespan_years
        net_cost = self.investment.net_cost

        yearly_results = []
        cumulative = 0.0
        payback_year = None

        for y in range(lifespan):
            result = self.calculate_yearly(y, sc_pct, cumulative)
            yearly_results.append(result)
            cumulative = result.cumulative_gain_chf

            if payback_year is None and cumulative >= net_cost:
                # Interpoler le mois exact
                prev_cumul = yearly_results[-2].cumulative_gain_chf if len(yearly_results) > 1 else 0
                monthly_gain = (cumulative - prev_cumul) / 12
                months_in_year = max(1, round((net_cost - prev_cumul) / max(monthly_gain, 1)))
                payback_year = y + months_in_year / 12

        total_production = sum(r.production_kwh for r in yearly_results)
        total_gains = cumulative
        total_maintenance = sum(r.maintenance_cost_chf for r in yearly_results)
        total_exceptional = sum(r.exceptional_cost_chf for r in yearly_results)
        total_costs = net_cost + total_maintenance + total_exceptional

        # LCOE (Levelized Cost of Energy) en ct/kWh
        lcoe = total_costs / max(total_production, 1) * 100

        start_year = int(self.investment.commissioning_date[:4])

        return {
            "summary": {
                "net_investment_chf": round(net_cost, 2),
                "total_cost_chf": round(self.investment.total_cost, 2),
                "subsidy_pronovo_chf": round(self.investment.subsidy_pronovo, 2),
                "subsidy_other_chf": round(self.investment.subsidy_other, 2),
                "payback_years": round(payback_year, 1) if payback_year else None,
                "payback_date": f"{start_year + int(payback_year)}" if payback_year else "N/A",
                "total_production_kwh": round(total_production, 0),
                "total_gains_chf": round(total_gains, 2),
                "total_profit_chf": round(total_gains - net_cost - total_maintenance - total_exceptional, 2),
                "roi_25y_pct": round(total_gains / max(net_cost, 1) * 100, 1),
                "lcoe_ct_kwh": round(lcoe, 1),
                "avg_annual_gain_chf": round(total_gains / lifespan, 2),
                "self_consumption_pct": sc_pct,
                "annual_degradation_pct": self.investment.annual_degradation_pct,
                "electricity_price_increase_pct": self.investment.electricity_price_increase_pct,
            },
            "yearly": yearly_results,
        }

    def sensitivity_analysis(self) -> list:
        """Analyse de sensibilité : amortissement pour différents taux d'autoconsommation.

        Returns:
            Liste de résumés pour chaque scénario (20%, 30%, 40%, 50%, 60%, 70%).
        """
        scenarios = []
        for pct in [20, 30, 35, 40, 50, 60, 70]:
            result = self.calculate_amortization(self_consumption_pct=pct)
            summary = result["summary"]
            summary["scenario_label"] = f"{pct}% autoconso"
            scenarios.append(summary)
        return scenarios
