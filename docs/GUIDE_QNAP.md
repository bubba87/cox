# Guide de Deploiement QNAP

Guide pas-a-pas pour deployer PCQ sur un NAS QNAP avec Container Station.

## Prerequis

- QNAP avec **Container Station** installe (QTS App Center)
- L'onduleur Huawei SUN2000 sur le meme reseau local que le QNAP
- Acces SSH au QNAP (optionnel mais recommande)

## Etape 1 : Preparer le QNAP

### 1.1 Installer Container Station

1. Ouvrir **QTS** dans le navigateur (`http://<IP-QNAP>:8080`)
2. Aller dans **App Center**
3. Chercher **Container Station** et l'installer
4. Ouvrir Container Station, il installera Docker automatiquement

### 1.2 Activer SSH (recommande)

1. **Panneau de configuration** > **Reseau et services de fichiers** > **Telnet / SSH**
2. Cocher **Autoriser la connexion SSH** (port 22)
3. Se connecter : `ssh admin@<IP-QNAP>`

### 1.3 Creer le dossier du projet

```bash
# Via SSH sur le QNAP
mkdir -p /share/Container/pcq
cd /share/Container/pcq
```

## Etape 2 : Transferer les fichiers

### Option A : Via SSH / SCP (recommande)

Depuis votre PC :

```bash
# Copier tout le projet sur le QNAP
scp -r ./* admin@<IP-QNAP>:/share/Container/pcq/
```

### Option B : Via l'interface web QTS

1. **File Station** > Naviguer vers `/Container/pcq/`
2. Glisser-deposer les fichiers du projet

### Fichiers necessaires

```
/share/Container/pcq/
├── Dockerfile
├── docker-compose.yml
├── .env                  # A creer depuis .env.example
├── .streamlit/
│   └── config.toml
└── pcq/
    ├── requirements.txt
    ├── config/
    ├── api/
    ├── dashboard/
    ├── models/
    ├── utils/
    ├── collector.py
    └── __main__.py
```

## Etape 3 : Configurer

### 3.1 Creer le fichier .env

```bash
cd /share/Container/pcq
cp pcq/.env.example .env
```

Editer `.env` :

```bash
vi .env
```

```ini
# IP de l'onduleur sur votre reseau local
INVERTER_IP=192.168.1.100

# Intervalle de collecte (60 = 1 minute)
COLLECT_INTERVAL=60

# Mode cloud uniquement (optionnel) :
# HUAWEI_FUSIONSOLAR_USER=votre_email@example.com
# HUAWEI_FUSIONSOLAR_PASS=votre_mot_de_passe
# HUAWEI_STATION_CODE=votre_code_station
```

> **Important** : Remplacez `192.168.1.100` par l'IP reelle de votre
> onduleur. Voir la section "Trouver l'IP de l'onduleur" ci-dessous.

### 3.2 Trouver l'IP de l'onduleur

L'onduleur Huawei est connecte via le dongle SDongleA-05.
Pour trouver son IP :

1. **Application FusionSolar** (telephone) :
   Parametres > Communication > Ethernet > Adresse IP

2. **Interface admin du routeur** :
   Chercher un appareil nomme "SDongle" ou "SUN2000" dans la liste DHCP

3. **Scan reseau** (depuis le QNAP) :
   ```bash
   # Si nmap est installe
   nmap -sP 192.168.1.0/24 | grep -B2 "Huawei"

   # Sinon, tester les ports Modbus courants
   for ip in $(seq 1 254); do
     timeout 1 bash -c "echo >/dev/tcp/192.168.1.$ip/502" 2>/dev/null && echo "Onduleur trouve: 192.168.1.$ip"
   done
   ```

> **Conseil** : Attribuez une **IP fixe** a l'onduleur dans votre routeur
> (reservation DHCP) pour eviter qu'elle change.

## Etape 4 : Lancer avec Docker Compose

### 4.1 Via SSH (recommande)

```bash
cd /share/Container/pcq

# Construire et demarrer
docker-compose up -d --build

# Verifier que tout tourne
docker-compose ps

# Voir les logs du collecteur
docker-compose logs -f collector

# Voir les logs du dashboard
docker-compose logs -f dashboard
```

### 4.2 Via Container Station (interface web)

1. Ouvrir **Container Station**
2. Cliquer **Creer** > **Docker Compose**
3. Choisir le dossier `/share/Container/pcq/`
4. Container Station detectera le `docker-compose.yml`
5. Cliquer **Creer**

### 4.3 Verifier le bon fonctionnement

```bash
# Le collecteur devrait afficher les donnees
docker-compose logs --tail 20 collector

# Resultat attendu :
# PCQ Collecteur - Mode: local | Intervalle: 60s
# [14:32:15] Local: 12.3 kW | 45.6 kWh jour
# [14:33:15] Local: 12.1 kW | 45.8 kWh jour
```

## Etape 5 : Acceder au dashboard

Le dashboard est accessible depuis **n'importe quel appareil** sur le reseau local :

```
http://<IP-QNAP>:8501
```

Exemples :
- `http://192.168.1.50:8501` (IP du QNAP)
- `http://qnap.local:8501` (si mDNS fonctionne)

### Depuis un telephone/tablette

Ouvrez simplement l'URL dans le navigateur. Le dashboard Streamlit
est responsive et fonctionne bien sur mobile.

> **Astuce** : Ajoutez la page en favori ou sur l'ecran d'accueil
> pour un acces rapide.

## Etape 6 : Demarrage automatique

Docker Compose avec `restart: unless-stopped` assure que les conteneurs
redemarrent automatiquement apres un redemarrage du QNAP.

Pour verifier :

```bash
# Redemarrer le QNAP et verifier que les conteneurs sont relances
docker-compose ps
```

Si Container Station ne demarre pas les conteneurs automatiquement :

1. **Panneau de configuration** > **Applications** > **Container Station**
2. Verifier que **Demarrage automatique** est active

## Maintenance

### Voir la taille de la base de donnees

```bash
docker-compose exec collector python -c "
from pcq.utils.database import Database
db = Database()
stats = db.get_db_stats()
for k, v in stats.items():
    print(f'{k}: {v}')
"
```

### Mise a jour du code

```bash
cd /share/Container/pcq

# Arreter
docker-compose down

# Mettre a jour les fichiers (git pull, scp, etc.)

# Reconstruire et relancer
docker-compose up -d --build
```

### Sauvegarder la base de donnees

```bash
# La DB est dans le volume Docker pcq-data
docker cp pcq-collector:/app/pcq/data/solar_data.db /share/Backup/solar_data_backup.db
```

Ou configurez une sauvegarde automatique via **Hybrid Backup Sync** du QNAP.

### Logs et diagnostic

```bash
# Logs en temps reel
docker-compose logs -f

# Logs du dernier jour
docker-compose logs --since 24h collector

# Redemarrer un seul service
docker-compose restart collector
docker-compose restart dashboard
```

## Depannage

| Probleme | Solution |
|----------|----------|
| Dashboard inaccessible | Verifier `docker-compose ps`, le port 8501 doit etre ouvert |
| "Connection refused" Modbus | Verifier l'IP onduleur, le Modbus doit etre active (voir guide ci-dessous) |
| Pas de donnees | Verifier les logs: `docker-compose logs collector` |
| Container ne demarre pas | `docker-compose logs` pour voir l'erreur |
| Performances lentes | Normal au debut, SQLite optimise le cache avec le temps |
| Port 8501 deja utilise | Changer le port dans `docker-compose.yml` : `"8502:8501"` |

## Architecture reseau

```
Internet
    │
    ▼
[Routeur / Box]──────────────────────────
    │            │            │
    ▼            ▼            ▼
[QNAP NAS]   [Onduleur]   [PC/Telephone]
 Docker        SUN2000      Navigateur
 ├─collector   Modbus:502   http://<QNAP>:8501
 └─dashboard
    :8501
```
