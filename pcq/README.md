# PCQ - Production, Consommation, Qualité

Système de monitoring solaire pour installation photovoltaïque **19 kWc** avec onduleur **Huawei SUN2000**.

## Fonctionnalités

- **Collecte de données** : API cloud FusionSolar ou Modbus TCP local
- **Monitoring temps réel** : puissance, production journalière, rendement
- **Prédiction de production** : modèle astronomique + météo (Open-Meteo)
- **Optimisation autoconsommation** : planning des appareils pour maximiser l'usage direct
- **Analyse financière** : comparaison injection vs autoconsommation

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
   - Coordonnées GPS de votre installation
   - Inclinaison et orientation des panneaux
   - Tarifs EDF (rachat OA, heures pleines/creuses)

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

### Dashboard web

```bash
streamlit run pcq/dashboard/app.py
```

Le dashboard s'ouvre sur http://localhost:8501

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
├── config/           # Configuration installation, tarifs, connexion
├── dashboard/        # Dashboard web Streamlit
├── data/             # Base de données SQLite
├── models/           # Prédiction + Optimisation
├── utils/            # Base de données, helpers
├── collector.py      # Collecteur de données périodique
└── __main__.py       # Point d'entrée CLI
```
