"""Dashboard web de monitoring solaire avec Streamlit.

Lance avec : streamlit run pcq/dashboard/app.py
Actualisation automatique configurable.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path


import streamlit as st

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pcq.config import AppConfig
from pcq.models.prediction import ProductionPredictor
from pcq.models.optimizer import SelfConsumptionOptimizer
from pcq.models.amortization import AmortizationCalculator
from pcq.api.tariff_updater import TariffUpdater
from pcq.utils.database import Database

# --- Configuration de la page ---
st.set_page_config(
    page_title="PCQ - Monitoring Solaire 19kW | Cudrefin",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Initialisation ---
config = AppConfig()
predictor = ProductionPredictor(config.installation)
optimizer = SelfConsumptionOptimizer(config)
db = Database(config.db_path)
tariff_updater = TariffUpdater(str(Path(config.db_path).parent))
amort_calc = AmortizationCalculator(config)

# --- Actualisation automatique ---
REFRESH_INTERVAL = config.refresh_interval_seconds


def get_current_quarter() -> int:
    """Retourne le trimestre actuel (1-4)."""
    return (datetime.now().month - 1) // 3 + 1


def get_current_feed_in_tariff() -> float:
    """Retourne le tarif de reprise selon le trimestre actuel."""
    q = get_current_quarter()
    tariffs = {
        1: config.tariff.feed_in_q1,
        2: config.tariff.feed_in_q2,
        3: config.tariff.feed_in_q3,
        4: config.tariff.feed_in_q4,
    }
    return tariffs.get(q, config.tariff.feed_in_tariff)


def render_header():
    col_title, col_refresh = st.columns([4, 1])
    with col_title:
        st.title("PCQ - Monitoring Solaire")
        st.caption(
            f"Installation {config.installation.peak_power_kwc} kWc | "
            f"Onduleur Huawei | {config.installation.location} | "
            f"Fournisseur: {config.tariff.provider}"
        )
    with col_refresh:
        st.caption(f"Dernière MAJ: {datetime.now():%H:%M:%S}")
        st.caption(f"Actualisation: {REFRESH_INTERVAL}s")


def render_realtime_section():
    """Section temps réel."""
    st.header("Temps Réel")

    latest = db.get_latest_production()
    current_feed_in = get_current_feed_in_tariff()

    col1, col2, col3, col4, col5 = st.columns(5)

    if latest:
        production = latest.get("power_kw", 0) or 0
        daily = latest.get("daily_yield_kwh", 0) or 0
        efficiency = latest.get("efficiency", 0) or 0
        temp = latest.get("inverter_temp", 0) or 0

        col1.metric("Production Actuelle", f"{production:.1f} kW")
        col2.metric("Production Jour", f"{daily:.1f} kWh")
        col3.metric("Rendement", f"{efficiency:.0f}%")
        col4.metric("Temp. Onduleur", f"{temp:.0f}°C")
        col5.metric(
            f"Tarif Reprise Q{get_current_quarter()}",
            f"{current_feed_in * 100:.1f} ct/kWh",
        )
    else:
        col1.metric("Production Actuelle", "-- kW")
        col2.metric("Production Jour", "-- kWh")
        col3.metric("Rendement", "--%")
        col4.metric("Temp. Onduleur", "--°C")
        col5.metric(
            f"Tarif Reprise Q{get_current_quarter()}",
            f"{current_feed_in * 100:.1f} ct/kWh",
        )
        st.info(
            "Aucune donnée temps réel disponible. "
            "Lancez le collecteur : `python -m pcq.collector`"
        )


def render_prediction_section():
    """Section prédiction de production."""
    st.header("Prédiction de Production")

    weather = predictor.get_weather_forecast(days=3)
    today_pred = predictor.predict_day(datetime.now(), weather)

    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Production Estimée Aujourd'hui",
        f"{today_pred['total_estimated_kwh']} kWh",
    )
    col2.metric("Pic de Puissance", f"{today_pred['peak_power_kw']} kW")
    col3.metric(
        "Plage Solaire",
        f"{today_pred['sunrise_approx']} - {today_pred['sunset_approx']}",
    )

    import pandas as pd

    hourly_data = today_pred["hourly"]
    df_hourly = pd.DataFrame(hourly_data)
    df_hourly["time_dt"] = pd.to_datetime(
        today_pred["date"] + " " + df_hourly["time"]
    )

    tab1, tab2 = st.tabs(["Production Horaire", "Prévision 7 Jours"])

    with tab1:
        chart_data = pd.DataFrame({
            "Heure": df_hourly["time_dt"],
            "Production (kW)": df_hourly["power_kw"],
            "Nuages (%)": df_hourly["cloud_cover"] * 100,
        }).set_index("Heure")
        st.line_chart(chart_data["Production (kW)"])
        st.caption("Couverture nuageuse")
        st.area_chart(chart_data["Nuages (%)"], color="#cccccc")

    with tab2:
        week_pred = predictor.predict_week()
        df_week = pd.DataFrame([
            {
                "Date": p["date"],
                "Production (kWh)": p["total_estimated_kwh"],
                "Pic (kW)": p["peak_power_kw"],
            }
            for p in week_pred
        ])
        st.bar_chart(df_week.set_index("Date")["Production (kWh)"])
        st.dataframe(df_week, use_container_width=True, hide_index=True)


def render_optimizer_section():
    """Section optimisation de l'autoconsommation."""
    st.header("Optimisation Autoconsommation")

    current_feed_in = get_current_feed_in_tariff()
    q = get_current_quarter()

    st.markdown(
        "**Principe** : Autoconsommer votre production est **toujours plus rentable** "
        "que réinjecter dans le réseau :\n"
        f"- Réinjection Q{q} = {current_feed_in * 100:.1f} ct/kWh "
        f"(tarif reprise Groupe E avec GO)\n"
        f"- Achat évité HT = {config.tariff.buy_price_peak * 100:.1f} ct/kWh "
        f"(haut tarif Groupe E)\n"
        f"- **Gain net par kWh autoconsommé = "
        f"{(config.tariff.buy_price_peak - current_feed_in) * 100:.1f} ct CHF**\n\n"
        "*Bas tarif Groupe E 2026 : 12h-17h et 23h-07h (tous les jours)*"
    )

    weather = predictor.get_weather_forecast(days=1)
    today = predictor.predict_day(datetime.now(), weather)

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Appareils à planifier")
        selected = st.multiselect(
            "Sélectionnez les appareils",
            options=list(SelfConsumptionOptimizer.APPLIANCES.keys()),
            default=["lave_linge", "lave_vaisselle", "chauffe_eau"],
            format_func=lambda x: x.replace("_", " ").title(),
        )
        base_conso = st.slider(
            "Consommation de base du foyer (kW)",
            min_value=0.3,
            max_value=5.0,
            value=1.0,
            step=0.1,
        )

    with col2:
        if selected:
            schedule = optimizer.daily_schedule(
                today["hourly"],
                appliances=selected,
                base_consumption_kw=base_conso,
            )

            st.subheader("Planning Optimisé")

            for rec in schedule["schedule"]:
                name = rec["appliance"].replace("_", " ").title()
                st.success(
                    f"**{name}** : {rec['recommended_start']} → "
                    f"{rec['recommended_end']} | "
                    f"Autoconsommé: {rec['estimated_self_consumed_kwh']} kWh | "
                    f"Économie: {rec['estimated_savings_eur']:.3f} CHF"
                )

            st.divider()

            summary = schedule["summary"]
            mcol1, mcol2, mcol3 = st.columns(3)
            mcol1.metric(
                "Taux d'Autoconsommation",
                f"{summary['self_consumption_rate']:.0f}%",
            )
            mcol2.metric(
                "Surplus Réinjecté",
                f"{summary['estimated_surplus_kwh']:.1f} kWh",
            )
            mcol3.metric(
                "Économies Estimées",
                f"{summary['total_estimated_savings_eur']:.3f} CHF",
            )


def render_financial_section():
    """Section analyse financière."""
    st.header("Analyse Financière")

    today = datetime.now()
    start = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    summaries = db.get_daily_summaries(start, end)

    if summaries:
        import pandas as pd

        df = pd.DataFrame(summaries)
        col1, col2, col3, col4 = st.columns(4)

        total_prod = df["total_production_kwh"].sum()
        total_self = df["self_consumed_kwh"].sum()
        revenue = df["revenue_injection"].sum()
        savings = df["savings_self_consumption"].sum()

        col1.metric("Production 30j", f"{total_prod:.0f} kWh")
        col2.metric("Autoconsommé", f"{total_self:.0f} kWh")
        col3.metric("Revenu Injection", f"{revenue:.2f} CHF")
        col4.metric("Économies Autoconso", f"{savings:.2f} CHF")

        st.bar_chart(
            df[["date", "total_production_kwh", "self_consumed_kwh", "exported_kwh"]]
            .set_index("date")
        )
    else:
        st.info(
            "Pas encore de données historiques. "
            "Les résumés se construisent automatiquement avec le collecteur."
        )

    # Projection annuelle
    st.subheader("Projection Annuelle")
    week = predictor.predict_week()
    avg_daily = sum(p["total_estimated_kwh"] for p in week) / len(week)

    col1, col2, col3 = st.columns(3)
    annual_prod = avg_daily * 365
    avg_feed_in = (
        config.tariff.feed_in_q1 + config.tariff.feed_in_q2
        + config.tariff.feed_in_q3 + config.tariff.feed_in_q4
    ) / 4
    annual_revenue_full_injection = annual_prod * avg_feed_in
    annual_savings_full_self = annual_prod * config.tariff.buy_price_peak

    col1.metric(
        "Production Annuelle Estimée",
        f"{annual_prod:.0f} kWh",
    )
    col2.metric(
        "Si 100% Réinjection",
        f"{annual_revenue_full_injection:.0f} CHF/an",
    )
    col3.metric(
        "Si 100% Autoconsommation",
        f"{annual_savings_full_self:.0f} CHF/an",
    )

    # Détail trimestriel des tarifs de reprise
    st.subheader("Tarifs de Reprise Groupe E par Trimestre")
    import pandas as pd
    df_tariffs = pd.DataFrame({
        "Trimestre": ["Q1 (Jan-Mar)", "Q2 (Avr-Jun)", "Q3 (Jul-Sep)", "Q4 (Oct-Déc)"],
        "Tarif (ct/kWh)": [
            config.tariff.feed_in_q1 * 100,
            config.tariff.feed_in_q2 * 100,
            config.tariff.feed_in_q3 * 100,
            config.tariff.feed_in_q4 * 100,
        ],
        "Saison": ["Hiver (GO 3ct)", "Été (GO 1ct)", "Été (GO 1ct)", "Hiver (GO 3ct)"],
    })
    st.dataframe(df_tariffs, use_container_width=True, hide_index=True)
    st.caption(
        "Tarifs basés sur les prix du marché OFEN, ajustés trimestriellement. "
        "Prix plancher garanti : 6 ct/kWh (sans GO) / 10 ct/kWh (avec GO) pour < 30 kW."
    )

    # Historique des tarifs
    tariff_history = db.get_tariff_history()
    if tariff_history:
        st.subheader("Historique des Tarifs")
        df_th = pd.DataFrame(tariff_history)
        cols_display = ["year", "quarter", "buy_price_peak", "buy_price_offpeak",
                        "feed_in_tariff", "source", "timestamp"]
        cols_present = [c for c in cols_display if c in df_th.columns]
        st.dataframe(df_th[cols_present], use_container_width=True, hide_index=True)


def render_amortization_section():
    """Section amortissement et retour sur investissement."""
    st.header("Amortissement")

    import pandas as pd

    inv = config.investment

    # KPIs en haut
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Coût Installation", f"{inv.total_cost:,.0f} CHF")
    col2.metric("Subvention Pronovo", f"-{inv.subsidy_pronovo:,.0f} CHF")
    col3.metric("Autres Subventions", f"-{inv.subsidy_other:,.0f} CHF")
    col4.metric("Investissement Net", f"{inv.net_cost:,.0f} CHF")

    # Calcul principal
    result = amort_calc.calculate_amortization()
    summary = result["summary"]

    st.subheader("Retour sur Investissement")

    col1, col2, col3, col4 = st.columns(4)
    payback = summary["payback_years"]
    col1.metric(
        "Amortissement",
        f"{payback:.1f} ans" if payback else "N/A",
        delta=f"en {summary['payback_date']}" if payback else None,
    )
    col2.metric("Gain Total (25 ans)", f"{summary['total_gains_chf']:,.0f} CHF")
    col3.metric("Profit Net (25 ans)", f"{summary['total_profit_chf']:,.0f} CHF")
    col4.metric("LCOE", f"{summary['lcoe_ct_kwh']:.1f} ct/kWh")

    col1, col2, col3 = st.columns(3)
    col1.metric("ROI sur 25 ans", f"{summary['roi_25y_pct']:.0f}%")
    col2.metric("Gain Annuel Moyen", f"{summary['avg_annual_gain_chf']:,.0f} CHF/an")
    col3.metric("Production Totale", f"{summary['total_production_kwh']:,.0f} kWh")

    # Graphique d'amortissement
    st.subheader("Courbe d'Amortissement")
    yearly = result["yearly"]

    df_amort = pd.DataFrame([{
        "Année": r.year,
        "Gain Cumulé (CHF)": r.cumulative_gain_chf,
        "Investissement Net": inv.net_cost,
    } for r in yearly])

    st.line_chart(
        df_amort.set_index("Année"),
        color=["#2ecc71", "#e74c3c"],
    )

    if payback:
        start_year = int(inv.commissioning_date[:4])
        st.caption(
            f"Point d'amortissement atteint en **{summary['payback_date']}** "
            f"({payback:.1f} ans). "
            f"Après cette date, chaque kWh produit est du profit net."
        )

    # Tableau détaillé
    with st.expander("Détail Année par Année"):
        df_detail = pd.DataFrame([{
            "Année": r.year,
            "Production (kWh)": f"{r.production_kwh:,.0f}",
            "Autoconsommé (kWh)": f"{r.self_consumed_kwh:,.0f}",
            "Revenu Injection": f"{r.revenue_injection_chf:,.2f}",
            "Économies Autoconso": f"{r.savings_self_consumption_chf:,.2f}",
            "Gain Brut": f"{r.total_gain_chf:,.2f}",
            "Maintenance": f"-{r.maintenance_cost_chf:,.2f}",
            "Exceptionnel": f"-{r.exceptional_cost_chf:,.2f}" if r.exceptional_cost_chf > 0 else "-",
            "Gain Net": f"{r.net_gain_chf:,.2f}",
            "Cumulé": f"{r.cumulative_gain_chf:,.2f}",
            "ROI": f"{r.roi_pct:.1f}%",
        } for r in yearly])
        st.dataframe(df_detail, use_container_width=True, hide_index=True)

    # Analyse de sensibilité
    st.subheader("Sensibilité au Taux d'Autoconsommation")
    st.caption(
        "L'amortissement dépend fortement de votre taux d'autoconsommation. "
        "Plus vous consommez directement, plus le retour est rapide."
    )

    scenarios = amort_calc.sensitivity_analysis()
    df_sens = pd.DataFrame([{
        "Scénario": s["scenario_label"],
        "Amortissement": f"{s['payback_years']:.1f} ans" if s["payback_years"] else "N/A",
        "Profit 25 ans": f"{s['total_profit_chf']:,.0f} CHF",
        "ROI": f"{s['roi_25y_pct']:.0f}%",
        "Gain/an": f"{s['avg_annual_gain_chf']:,.0f} CHF",
    } for s in scenarios])
    st.dataframe(df_sens, use_container_width=True, hide_index=True)

    # Graphique comparatif
    df_sens_chart = pd.DataFrame([{
        "Autoconsommation (%)": int(s["self_consumption_pct"]),
        "Amortissement (années)": s["payback_years"] or 30,
    } for s in scenarios]).set_index("Autoconsommation (%)")
    st.bar_chart(df_sens_chart)

    st.caption(
        f"Hypothèses : dégradation {inv.annual_degradation_pct}%/an, "
        f"hausse électricité {inv.electricity_price_increase_pct}%/an, "
        f"remplacement onduleur à {inv.inverter_lifespan_years} ans "
        f"({inv.inverter_replacement_cost:,.0f} CHF), "
        f"maintenance {inv.annual_maintenance_cost:,.0f} CHF/an."
    )


def render_settings_sidebar():
    """Barre latérale de configuration."""
    with st.sidebar:
        st.header("Configuration")

        st.subheader("Installation")
        config.installation.peak_power_kwc = st.number_input(
            "Puissance crête (kWc)", value=config.installation.peak_power_kwc
        )
        config.installation.latitude = st.number_input(
            "Latitude", value=config.installation.latitude, format="%.4f"
        )
        config.installation.longitude = st.number_input(
            "Longitude", value=config.installation.longitude, format="%.4f"
        )
        config.installation.tilt = st.slider(
            "Inclinaison panneaux (°)", 0, 90, int(config.installation.tilt)
        )
        config.installation.azimuth = st.slider(
            "Azimut (°, 180=Sud)", 0, 360, int(config.installation.azimuth)
        )

        st.subheader("Tarifs Groupe E (CHF/kWh)")

        # Bouton de mise à jour automatique
        if st.button("Mettre à jour les tarifs"):
            changes = tariff_updater.update_tariffs(config.tariff)
            if changes:
                db.insert_tariff_snapshot(config.tariff, source="manuel")
                st.success(f"Tarifs mis à jour : {len(changes)} changement(s)")
                for k, v in changes.items():
                    st.caption(f"  {k}: {v['old']} → {v['new']}")
            else:
                st.info("Tarifs déjà à jour")

        tariff_status = tariff_updater.get_tariff_status()
        st.caption(f"Dernière MAJ: {tariff_status['last_update']}")

        config.tariff.feed_in_tariff = st.number_input(
            "Tarif reprise moyen (CHF/kWh)",
            value=config.tariff.feed_in_tariff,
            format="%.4f",
        )
        config.tariff.buy_price_peak = st.number_input(
            "Prix achat HT (CHF/kWh)",
            value=config.tariff.buy_price_peak,
            format="%.4f",
        )
        config.tariff.buy_price_offpeak = st.number_input(
            "Prix achat BT (CHF/kWh)",
            value=config.tariff.buy_price_offpeak,
            format="%.4f",
        )

        # Tarifs trimestriels de reprise
        with st.expander("Tarifs reprise par trimestre"):
            config.tariff.feed_in_q1 = st.number_input(
                "Q1 Jan-Mar (CHF/kWh)", value=config.tariff.feed_in_q1, format="%.4f", key="q1"
            )
            config.tariff.feed_in_q2 = st.number_input(
                "Q2 Avr-Jun (CHF/kWh)", value=config.tariff.feed_in_q2, format="%.4f", key="q2"
            )
            config.tariff.feed_in_q3 = st.number_input(
                "Q3 Jul-Sep (CHF/kWh)", value=config.tariff.feed_in_q3, format="%.4f", key="q3"
            )
            config.tariff.feed_in_q4 = st.number_input(
                "Q4 Oct-Déc (CHF/kWh)", value=config.tariff.feed_in_q4, format="%.4f", key="q4"
            )
            if st.button("Sauvegarder tarifs trimestriels"):
                now = datetime.now()
                for q, rate in enumerate(
                    [config.tariff.feed_in_q1, config.tariff.feed_in_q2,
                     config.tariff.feed_in_q3, config.tariff.feed_in_q4], 1
                ):
                    tariff_updater.set_quarterly_feed_in(q, rate, now.year)
                db.insert_tariff_snapshot(config.tariff, source="manuel_sidebar")
                st.success("Tarifs trimestriels sauvegardés")

        st.subheader("Investissement")
        config.investment.total_cost = st.number_input(
            "Coût total installation (CHF)",
            value=config.investment.total_cost,
            step=500.0,
            format="%.0f",
        )
        config.investment.subsidy_pronovo = st.number_input(
            "Subvention Pronovo (CHF)",
            value=config.investment.subsidy_pronovo,
            step=100.0,
            format="%.0f",
        )
        config.investment.subsidy_other = st.number_input(
            "Autres subventions (CHF)",
            value=config.investment.subsidy_other,
            step=100.0,
            format="%.0f",
        )
        with st.expander("Paramètres avancés"):
            config.investment.estimated_self_consumption_pct = st.slider(
                "Taux autoconsommation (%)", 10, 90,
                int(config.investment.estimated_self_consumption_pct),
            )
            config.investment.annual_degradation_pct = st.number_input(
                "Dégradation panneaux (%/an)",
                value=config.investment.annual_degradation_pct,
                format="%.2f", step=0.1,
            )
            config.investment.electricity_price_increase_pct = st.number_input(
                "Hausse prix élec. (%/an)",
                value=config.investment.electricity_price_increase_pct,
                format="%.1f", step=0.5,
            )
            config.investment.annual_maintenance_cost = st.number_input(
                "Maintenance annuelle (CHF)",
                value=config.investment.annual_maintenance_cost,
                format="%.0f", step=50.0,
            )
            config.investment.inverter_replacement_cost = st.number_input(
                "Remplacement onduleur (CHF)",
                value=config.investment.inverter_replacement_cost,
                format="%.0f", step=500.0,
            )
            config.investment.inverter_lifespan_years = st.number_input(
                "Durée vie onduleur (ans)",
                value=config.investment.inverter_lifespan_years,
                step=1,
            )
            config.investment.commissioning_date = st.text_input(
                "Date mise en service",
                value=config.investment.commissioning_date,
            )

        st.subheader("Actualisation")
        refresh = st.selectbox(
            "Intervalle (secondes)",
            options=[30, 60, 120, 300],
            index=[30, 60, 120, 300].index(REFRESH_INTERVAL)
            if REFRESH_INTERVAL in [30, 60, 120, 300]
            else 1,
        )

        st.divider()
        st.caption(
            f"PCQ v0.1.0 | {config.installation.location} | "
            f"{config.installation.peak_power_kwc} kWc | {config.tariff.provider}"
        )

        return refresh


# --- MAIN ---
def main():
    refresh = render_settings_sidebar()
    render_header()
    render_realtime_section()
    st.divider()
    render_prediction_section()
    st.divider()
    render_optimizer_section()
    st.divider()
    render_financial_section()
    st.divider()
    render_amortization_section()

    # Auto-refresh
    import time
    time.sleep(refresh)
    st.rerun()


if __name__ == "__main__":
    main()
else:
    main()
