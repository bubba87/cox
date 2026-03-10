"""Dashboard web de monitoring solaire avec Streamlit.

Lance avec : streamlit run pcq/dashboard/app.py
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
from pcq.utils.database import Database

# --- Configuration de la page ---
st.set_page_config(
    page_title="PCQ - Monitoring Solaire 19kW",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Initialisation ---
config = AppConfig()
predictor = ProductionPredictor(config.installation)
optimizer = SelfConsumptionOptimizer(config)
db = Database(config.db_path)


def render_header():
    st.title("PCQ - Monitoring Solaire")
    st.caption(f"Installation {config.installation.peak_power_kwc} kWc | Onduleur Huawei")


def render_realtime_section():
    """Section temps réel."""
    st.header("Temps Réel")

    latest = db.get_latest_production()

    col1, col2, col3, col4 = st.columns(4)

    if latest:
        production = latest.get("power_kw", 0) or 0
        daily = latest.get("daily_yield_kwh", 0) or 0
        efficiency = latest.get("efficiency", 0) or 0
        temp = latest.get("inverter_temp", 0) or 0

        col1.metric("Production Actuelle", f"{production:.1f} kW", delta=None)
        col2.metric("Production Jour", f"{daily:.1f} kWh")
        col3.metric("Rendement", f"{efficiency:.0f}%")
        col4.metric("Temp. Onduleur", f"{temp:.0f}°C")
    else:
        col1.metric("Production Actuelle", "-- kW")
        col2.metric("Production Jour", "-- kWh")
        col3.metric("Rendement", "--%")
        col4.metric("Temp. Onduleur", "--°C")
        st.info(
            "Aucune donnée temps réel disponible. "
            "Lancez le collecteur : `python -m pcq.collector`"
        )


def render_prediction_section():
    """Section prédiction de production."""
    st.header("Prédiction de Production")

    # Prévision du jour
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

    # Graphique de production horaire
    hourly_data = today_pred["hourly"]
    times = [h["time"] for h in hourly_data]
    powers = [h["power_kw"] for h in hourly_data]
    clouds = [h["cloud_cover"] * 100 for h in hourly_data]

    import pandas as pd

    # Sous-échantillonner pour lisibilité (1 point par heure)
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

    st.markdown("""
    **Principe** : Autoconsommer votre production est **toujours plus rentable**
    que réinjecter dans le réseau :
    - Réinjection = {feed_in:.4f} €/kWh (tarif OA)
    - Achat évité = {buy:.4f} €/kWh (heures pleines)
    - **Gain net par kWh autoconsommé = {gain:.4f} €**
    """.format(
        feed_in=config.tariff.feed_in_tariff,
        buy=config.tariff.buy_price_peak,
        gain=config.tariff.buy_price_peak - config.tariff.feed_in_tariff,
    ))

    # Prédiction pour l'optimisation
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
                    f"Économie: {rec['estimated_savings_eur']:.3f} €"
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
                f"{summary['total_estimated_savings_eur']:.3f} €",
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
        total_export = df["exported_kwh"].sum()
        total_self = df["self_consumed_kwh"].sum()
        revenue = df["revenue_injection"].sum()
        savings = df["savings_self_consumption"].sum()

        col1.metric("Production 30j", f"{total_prod:.0f} kWh")
        col2.metric("Autoconsommé", f"{total_self:.0f} kWh")
        col3.metric("Revenu Injection", f"{revenue:.2f} €")
        col4.metric("Économies Autoconso", f"{savings:.2f} €")

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
    # Estimation basée sur la prédiction
    week = predictor.predict_week()
    avg_daily = sum(p["total_estimated_kwh"] for p in week) / len(week)

    col1, col2, col3 = st.columns(3)
    annual_prod = avg_daily * 365
    annual_revenue_full_injection = annual_prod * config.tariff.feed_in_tariff
    annual_savings_full_self = annual_prod * config.tariff.buy_price_peak

    col1.metric(
        "Production Annuelle Estimée",
        f"{annual_prod:.0f} kWh",
    )
    col2.metric(
        "Si 100% Réinjection",
        f"{annual_revenue_full_injection:.0f} €/an",
    )
    col3.metric(
        "Si 100% Autoconsommation",
        f"{annual_savings_full_self:.0f} €/an",
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

        st.subheader("Tarifs")
        config.tariff.feed_in_tariff = st.number_input(
            "Tarif rachat OA (€/kWh)",
            value=config.tariff.feed_in_tariff,
            format="%.4f",
        )
        config.tariff.buy_price_peak = st.number_input(
            "Prix achat HP (€/kWh)",
            value=config.tariff.buy_price_peak,
            format="%.4f",
        )
        config.tariff.buy_price_offpeak = st.number_input(
            "Prix achat HC (€/kWh)",
            value=config.tariff.buy_price_offpeak,
            format="%.4f",
        )

        st.divider()
        st.caption("PCQ v0.1.0 | Monitoring Solaire Huawei 19kW")


# --- MAIN ---
def main():
    render_settings_sidebar()
    render_header()
    render_realtime_section()
    st.divider()
    render_prediction_section()
    st.divider()
    render_optimizer_section()
    st.divider()
    render_financial_section()


if __name__ == "__main__":
    main()
else:
    # Exécuté par streamlit run
    main()
