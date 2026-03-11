"""Mise à jour automatique des tarifs électriques suisses.

Sources :
- ElCom (Commission fédérale de l'électricité) : tarifs de réseau
- OFEN / prix du marché : tarifs de reprise solaire
- Groupe E : tarifs spécifiques du fournisseur

Les tarifs de reprise sont ajustés trimestriellement par Groupe E
sur la base des prix du marché spot (EPEX SPOT CH).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# URL de l'API ElCom pour les tarifs par commune
# NPA Cudrefin = 1588
ELCOM_API_URL = "https://www.prix-electricite.elcom.admin.ch/api/period/{year}/municipality/{municipality_id}"

# Tarifs planchers garantis pour installations < 30 kW (Suisse)
MIN_FEED_IN_WITHOUT_GO = 0.06   # 6 ct/kWh sans garantie d'origine
MIN_FEED_IN_WITH_GO = 0.10      # 10 ct/kWh avec GO


class TariffUpdater:
    """Met à jour les tarifs depuis les sources officielles suisses."""

    def __init__(self, cache_dir: str = "pcq/data"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "tariff_cache.json"

    def _load_cache(self) -> dict:
        if self.cache_file.exists():
            try:
                return json.loads(self.cache_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_cache(self, data: dict):
        self.cache_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def fetch_elcom_tariffs(
        self,
        municipality_id: int = 848,  # Cudrefin
        year: Optional[int] = None,
        category: str = "H4",  # Ménage 4500 kWh/an
    ) -> Optional[dict]:
        """Récupère les tarifs depuis l'API ElCom.

        Categories ElCom :
        - H1: Ménage 1600 kWh/an
        - H2: Ménage 2500 kWh/an
        - H3: Ménage 4500 kWh/an (mono-tarif)
        - H4: Ménage 4500 kWh/an (double tarif HT/BT)
        - H7: Ménage 13'000 kWh/an avec PAC
        """
        year = year or datetime.now().year
        url = ELCOM_API_URL.format(year=year, municipality_id=municipality_id)

        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            # Chercher la catégorie demandée dans les résultats
            for entry in data if isinstance(data, list) else [data]:
                if entry.get("category") == category or not entry.get("category"):
                    return {
                        "source": "ElCom",
                        "year": year,
                        "municipality_id": municipality_id,
                        "category": category,
                        "total_ht_chf_kwh": entry.get("total", entry.get("totalInclVat")),
                        "energy_chf_kwh": entry.get("energy"),
                        "grid_chf_kwh": entry.get("gridUsage"),
                        "taxes_chf_kwh": entry.get("communityFees"),
                        "raw": entry,
                    }
            return None

        except requests.RequestException as e:
            logger.warning(f"ElCom API indisponible: {e}")
            return None

    def fetch_groupe_e_tariffs(self) -> Optional[dict]:
        """Récupère les tarifs Groupe E depuis leur page tarifaire.

        Groupe E publie ses tarifs sur :
        https://www.groupe-e.ch/fr/tarifs-electricite

        En l'absence d'API publique, on utilise les tarifs connus
        et on met à jour le cache manuellement ou via scraping.
        """
        # Groupe E n'a pas d'API publique pour les tarifs.
        # On utilise les tarifs officiels 2026 connus.
        # Cette méthode pourra être étendue avec du scraping si nécessaire.
        return None

    def estimate_quarterly_feed_in(self, quarter: int, year: Optional[int] = None) -> float:
        """Estime le tarif de reprise trimestriel.

        Basé sur les prix spot EPEX SPOT CH + prime GO.
        Groupe E ajuste trimestriellement.

        Fourchettes typiques :
        - Hiver (Q1, Q4) : 10-15 ct/kWh (prix marché élevé + GO 3ct)
        - Été (Q2, Q3) : 6-10 ct/kWh (prix marché bas + GO 1ct)
        """
        cache = self._load_cache()
        year = year or datetime.now().year
        key = f"feed_in_{year}_q{quarter}"

        if key in cache:
            return cache[key]

        # Valeurs par défaut basées sur les tendances historiques
        defaults = {
            1: 0.138,  # Q1 hiver
            2: 0.086,  # Q2 été
            3: 0.086,  # Q3 été
            4: 0.138,  # Q4 hiver
        }
        return defaults.get(quarter, 0.10)

    def update_tariffs(self, tariff_config) -> dict:
        """Met à jour la configuration des tarifs avec les données les plus récentes.

        Args:
            tariff_config: Instance de TariffConfig à mettre à jour.

        Returns:
            Dict avec les changements effectués.
        """
        changes = {}
        cache = self._load_cache()
        now = datetime.now()

        # 1. Essayer ElCom pour les tarifs d'achat
        elcom = self.fetch_elcom_tariffs()
        if elcom and elcom.get("total_ht_chf_kwh"):
            old_peak = tariff_config.buy_price_peak
            new_total = elcom["total_ht_chf_kwh"]
            if abs(new_total - old_peak) > 0.001:
                tariff_config.buy_price_peak = new_total
                changes["buy_price_peak"] = {"old": old_peak, "new": new_total}
                logger.info(f"Tarif HT mis à jour: {old_peak} -> {new_total} CHF/kWh")

        # 2. Mettre à jour les tarifs de reprise trimestriels
        for q in range(1, 5):
            rate = self.estimate_quarterly_feed_in(q, now.year)
            attr = f"feed_in_q{q}"
            old = getattr(tariff_config, attr)
            if abs(rate - old) > 0.001:
                setattr(tariff_config, attr, rate)
                changes[attr] = {"old": old, "new": rate}

        # 3. Recalculer le tarif moyen de reprise
        avg = (
            tariff_config.feed_in_q1 + tariff_config.feed_in_q2
            + tariff_config.feed_in_q3 + tariff_config.feed_in_q4
        ) / 4
        if abs(avg - tariff_config.feed_in_tariff) > 0.001:
            old_avg = tariff_config.feed_in_tariff
            tariff_config.feed_in_tariff = round(avg, 4)
            changes["feed_in_tariff_avg"] = {"old": old_avg, "new": round(avg, 4)}

        # 4. Sauvegarder dans le cache
        cache["last_update"] = now.isoformat()
        cache["changes"] = changes
        cache["current_tariffs"] = {
            "buy_price_peak": tariff_config.buy_price_peak,
            "buy_price_offpeak": tariff_config.buy_price_offpeak,
            "feed_in_q1": tariff_config.feed_in_q1,
            "feed_in_q2": tariff_config.feed_in_q2,
            "feed_in_q3": tariff_config.feed_in_q3,
            "feed_in_q4": tariff_config.feed_in_q4,
            "feed_in_tariff": tariff_config.feed_in_tariff,
        }
        self._save_cache(cache)

        return changes

    def set_quarterly_feed_in(self, quarter: int, rate: float, year: Optional[int] = None):
        """Enregistre manuellement un tarif de reprise trimestriel.

        Utile quand Groupe E publie les nouveaux tarifs chaque trimestre.

        Args:
            quarter: 1-4
            rate: Tarif en CHF/kWh (ex: 0.138)
            year: Année (défaut: année en cours)
        """
        year = year or datetime.now().year
        cache = self._load_cache()
        cache[f"feed_in_{year}_q{quarter}"] = rate
        cache[f"feed_in_{year}_q{quarter}_updated"] = datetime.now().isoformat()
        self._save_cache(cache)
        logger.info(f"Tarif reprise {year} Q{quarter} enregistré: {rate} CHF/kWh")

    def get_tariff_status(self) -> dict:
        """Retourne l'état actuel des tarifs et la date de dernière mise à jour."""
        cache = self._load_cache()
        return {
            "last_update": cache.get("last_update", "jamais"),
            "current_tariffs": cache.get("current_tariffs", {}),
            "source": "ElCom + cache local",
        }
