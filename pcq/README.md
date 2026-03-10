# PCQ - Production, Consommation, Qualité

Système de monitoring solaire pour installation photovoltaïque **19 kWc** avec onduleur **Huawei SUN2000** à **Cudrefin, Suisse** (fournisseur: **Groupe E**).

## Fonctionnalités

- **Collecte de données** : API cloud FusionSolar ou Modbus TCP local
- **Monitoring temps réel** : puissance, production journalière, rendement (actualisation automatique)
- **Prédiction de production** : modèle astronomique + météo Open-Meteo (Cudrefin 46.95°N 7.02°E)
- **Optimisation autoconsommation** : planning des appareils pour maximiser l'usage direct
- **Analyse financière** : tarifs Groupe E 2026 en CHF, reprise trimestrielle OFEN

## Tarifs Groupe E 2026

| Tarif | Prix |
|-------|------|
| Haut tarif (HT) | 27.61 ct/kWh |
| Bas tarif (BT) | 21.17 ct/kWh |
| Heures BT | 12h-17h et 23h-07h (tous les jours) |
| Reprise solaire Q1/Q4 (hiver) | ~13.8 ct/kWh (avec GO) |
| Reprise solaire Q2/Q3 (été) | ~8.6 ct/kWh (avec GO) |
| Prix plancher < 30 kW | 10 ct/kWh (avec GO) |

## Installation

```bash
pip install -r pcq/requirements.txt
```

## Configuration

1. Copiez le fichier d'environnement :
```bash
cp pcq/.env.example .env
```

2. Éditez `.env` avec vos identifiants FusionSolar (optionnel, le mode démo fonctionne sans)

3. Ajustez la configuration dans `pcq/config/settings.py` :
   - Coordonnées GPS (défaut: Cudrefin)
   - Inclinaison et orientation des panneaux
   - Tarifs Groupe E en CHF

## Utilisation

### Collecteur de données

```bash
# Mode démo (données simulées)
python -m pcq --mode demo --interval 60

# Via l'API cloud FusionSolar
python -m pcq --mode cloud --interval 300

# Via Modbus TCP local (réseau local de l'onduleur)
python -m pcq --mode local --host 192.168.200.1 --interval 60
```

### Dashboard web (avec actualisation automatique)

```bash
streamlit run pcq/dashboard/app.py
```

Le dashboard s'ouvre sur http://localhost:8501 et s'actualise automatiquement (configurable: 30s, 60s, 120s, 300s).

## Modes de collecte

| Mode | Avantages | Prérequis |
|------|-----------|-----------|
| `demo` | Aucun prérequis, données simulées | Rien |
| `cloud` | Accès depuis n'importe où | Compte FusionSolar |
| `local` | Temps réel, pas de dépendance cloud | Réseau local onduleur + pymodbus |

## Architecture

```
pcq/
├── api/              # Clients API (FusionSolar cloud + Modbus local)
├── config/           # Configuration installation, tarifs Groupe E, connexion
├── dashboard/        # Dashboard web Streamlit (auto-refresh)
├── data/             # Base de données SQLite
├── models/           # Prédiction + Optimisation
├── utils/            # Base de données, helpers
├── collector.py      # Collecteur de données périodique
└── __main__.py       # Point d'entrée CLI
```
