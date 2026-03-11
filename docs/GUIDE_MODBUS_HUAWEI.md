# Activer Modbus TCP sur l'onduleur Huawei SUN2000

Guide pour activer la communication Modbus TCP sur l'onduleur Huawei SUN2000
via le dongle SDongleA-05 (WiFi/Ethernet).

## Pourquoi Modbus plutot que le Cloud ?

| | Cloud FusionSolar | Modbus TCP local |
|---|---|---|
| Latence | 30s - 5 min | < 1 seconde |
| Frequence max | 5 min | 1 seconde |
| Dependance Internet | Oui | Non |
| Disponibilite | 99% (maintenance Huawei) | 100% (reseau local) |
| Donnees disponibles | Limitees par l'API | Tous les registres |
| Configuration | Compte FusionSolar | Acces reseau local |

**Recommandation** : Modbus TCP local pour la collecte principale,
cloud FusionSolar en backup.

## Prerequis

- Onduleur Huawei **SUN2000** (serie 2-20 KTL ou similaire)
- Dongle de communication **SDongleA-05** (WiFi + Ethernet)
  ou **SDongleA-03** (WiFi uniquement)
- Cable Ethernet RJ45 entre le dongle et votre routeur/switch
- Smartphone avec l'application **FusionSolar** (iOS/Android)

## Etape 1 : Connexion physique

### 1.1 Localiser le dongle

Le dongle SDongleA-05 est branche sur le port **COM** de l'onduleur
(en bas de l'onduleur, sous le capot de protection).

```
┌──────────────────────────┐
│    HUAWEI SUN2000         │
│                           │
│  [AC]  [DC1]  [DC2]      │
│                           │
│  [COM]  ← Dongle ici     │
│   │                       │
│   ▼                       │
│  SDongleA-05              │
│  ┌─────────┐              │
│  │ LED ● ● │              │
│  │ [RJ45]  │ ← Cable     │
│  │ [Reset] │   Ethernet   │
│  └─────────┘              │
└──────────────────────────┘
```

### 1.2 Brancher le cable Ethernet

1. Branchez un **cable RJ45** entre le port Ethernet du dongle et
   votre routeur/switch reseau
2. Le dongle obtiendra automatiquement une IP via **DHCP**
3. La LED reseau du dongle doit passer au **vert fixe**

> **Important** : Le dongle et le QNAP doivent etre sur le **meme
> sous-reseau** (ex: 192.168.1.x). Si ce n'est pas le cas,
> configurez le routage ou mettez-les sur le meme switch.

## Etape 2 : Activer Modbus TCP via l'app FusionSolar

### 2.1 Se connecter a l'onduleur

1. Ouvrir l'application **FusionSolar** sur le telephone
2. Appuyer sur **"Appareil"** (icone en bas)
3. Se connecter a l'onduleur :
   - **Methode WiFi** : Se connecter au WiFi du dongle
     - SSID : `SUN2000-xxxxxxxxxx` (numero de serie)
     - Mot de passe par defaut : `Changeme` ou le numero de serie
   - **Methode Bluetooth** : Activer le Bluetooth et scanner

4. Identifiants de connexion a l'onduleur :
   - Utilisateur : `installer`
   - Mot de passe : `00000a` (defaut usine, changez-le !)

### 2.2 Configurer la communication

1. Aller dans **Parametres** (icone engrenage)
2. **Communication** > **Configuration du dongle**

### 2.3 Verifier la connexion Ethernet

1. Dans **Communication** > **Ethernet** :
   - Mode : **DHCP** (recommande) ou IP statique
   - Verifier que l'adresse IP est attribuee
   - **Noter cette adresse IP** (ex: `192.168.1.100`)

> **Astuce** : Si vous utilisez DHCP, configurez une **reservation
> d'adresse** dans votre routeur pour que l'IP ne change pas.

### 2.4 Activer Modbus TCP

C'est l'etape cle :

1. Dans **Parametres** > **Communication** :
2. Chercher **"Modbus TCP"** ou **"Protocol Modbus"**

   **Sur les firmwares recents (V200R001 et +)** :
   - **Communication** > **Parametres du dongle** > **Modbus TCP**
   - Activer : **ON**
   - Port : **502** (defaut, ne pas changer)
   - Adresse Modbus : **1** (defaut)

   **Sur les firmwares plus anciens** :
   - **Communication** > **Protocol Settings**
   - Protocol : choisir **Modbus TCP**
   - Connection : **Enable**

3. **Sauvegarder** les parametres

> **Note** : Sur certains modeles, Modbus est active par defaut.
> Verifiez simplement que le port 502 repond (voir etape 3).

### 2.5 Parametres Modbus detailles

| Parametre | Valeur |
|-----------|--------|
| Protocole | Modbus TCP |
| Port | 502 |
| Adresse esclave (Unit ID) | 1 |
| Timeout | 3000 ms |
| Nombre max de connexions | 5 |

## Etape 3 : Verifier la connexion

### 3.1 Test rapide (depuis le QNAP ou un PC)

```bash
# Tester si le port Modbus repond
nc -zv 192.168.1.100 502

# Resultat attendu :
# Connection to 192.168.1.100 502 port [tcp/*] succeeded!
```

### 3.2 Test avec Python

```bash
pip install pymodbus

python3 -c "
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('192.168.1.100', port=502)
if client.connect():
    # Lire la puissance active (registre 32080, 2 mots)
    result = client.read_holding_registers(32080, 2, slave=1)
    if not result.isError():
        raw = (result.registers[0] << 16) | result.registers[1]
        power_kw = raw / 1000
        print(f'Puissance active: {power_kw} kW')
    else:
        print(f'Erreur lecture: {result}')
    client.close()
else:
    print('Connexion impossible')
"
```

### 3.3 Test avec PCQ

```bash
# Depuis le dossier du projet
python -m pcq.collector --mode local --host 192.168.1.100 --interval 10

# Resultat attendu :
# PCQ Collecteur - Mode: local | Intervalle: 10s
# [14:32:15] Local: 12.3 kW | 45.6 kWh jour
```

## Etape 4 : Configurer PCQ pour Modbus

Editez le fichier `.env` :

```ini
# Remplacez par l'IP de votre onduleur
INVERTER_IP=192.168.1.100

# Collecte toutes les 60 secondes
COLLECT_INTERVAL=60
```

Le `docker-compose.yml` utilise ces variables automatiquement.

## Registres Modbus utilises par PCQ

Voici les registres que PCQ lit sur votre SUN2000 :

| Registre | Adresse | Taille | Echelle | Description |
|----------|---------|--------|---------|-------------|
| active_power | 32080 | 2 mots | /1000 | Puissance active (kW) |
| input_power | 32064 | 2 mots | /1000 | Puissance d'entree PV (kW) |
| daily_yield | 32114 | 2 mots | /100 | Production du jour (kWh) |
| total_yield | 32106 | 2 mots | /100 | Production totale (kWh) |
| grid_voltage | 32066 | 1 mot | /10 | Tension reseau (V) |
| grid_frequency | 32085 | 1 mot | /100 | Frequence reseau (Hz) |
| efficiency | 32086 | 1 mot | /100 | Rendement onduleur (%) |
| internal_temp | 32087 | 1 mot | /10 | Temperature interne (C) |
| pv1_voltage | 32016 | 1 mot | /10 | Tension string PV1 (V) |
| pv1_current | 32017 | 1 mot | /100 | Courant string PV1 (A) |
| pv2_voltage | 32018 | 1 mot | /10 | Tension string PV2 (V) |
| pv2_current | 32019 | 1 mot | /100 | Courant string PV2 (A) |
| grid_export_power | 37113 | 2 mots | /1 | Puissance exportee (W) |
| grid_import_power | 37119 | 2 mots | /1 | Puissance importee (W) |

> **Reference** : Documentation Huawei
> "SUN2000 Modbus Interface Definitions" (EDOC1100261860)

## Depannage

### "Connection refused" sur le port 502

1. Verifier que le cable Ethernet est branche au dongle
2. Verifier que le Modbus TCP est active (etape 2.4)
3. Ping l'onduleur : `ping 192.168.1.100`
4. Le dongle a peut-etre change d'IP → verifier dans le routeur

### "Timeout" lors de la lecture des registres

1. L'onduleur met quelques secondes a repondre au demarrage
2. Augmenter le timeout a 5 secondes
3. Verifier qu'il n'y a pas trop de clients Modbus connectes (max 5)

### Valeurs a zero

- **La nuit** : la puissance active est 0, c'est normal
- **Le jour** : verifier que les strings PV sont connectes
  (pv1_voltage / pv2_voltage doivent etre > 0)

### "Illegal address" sur certains registres

- Certains registres dependent du modele d'onduleur
- Les registres 37xxx (compteur reseau) necessitent un smart meter
  Huawei DTSU666 connecte
- Verifier la version du firmware de l'onduleur

### Le dongle ne se connecte pas au reseau

1. Verifier les LEDs :
   - **Verte fixe** : connecte
   - **Verte clignotante** : en cours de connexion
   - **Rouge** : erreur
2. Essayer un autre cable RJ45
3. Reinitialiser le dongle (bouton Reset, appui long 10s)

## Schema de connexion complet

```
┌──────────────────┐     Cable RJ45      ┌──────────────┐
│   Onduleur       │                      │   Routeur    │
│   SUN2000        │                      │              │
│                  │     ┌──────────┐     │  DHCP        │
│   [COM] ─────────┼─────│ SDongle  │─────┤  192.168.1.x │
│                  │     │ A-05     │     │              │
│                  │     │ Port 502 │     │              │
└──────────────────┘     └──────────┘     └──────┬───────┘
                                                  │
                         ┌────────────────────────┤
                         │                        │
                    ┌────▼─────┐          ┌───────▼──────┐
                    │ QNAP NAS │          │ PC/Telephone │
                    │          │          │              │
                    │ Docker   │          │ Dashboard    │
                    │ PCQ      │          │ :8501        │
                    │ Modbus──►│          │              │
                    │          │          │              │
                    └──────────┘          └──────────────┘
```

## Securite

- **Changez le mot de passe** de l'onduleur (defaut: `00000a`)
- Le Modbus TCP n'a **pas d'authentification** native.
  Assurez-vous que seul votre reseau local y accede
- Ne **jamais exposer** le port 502 sur Internet
- Si vous avez un VLAN IoT, placez l'onduleur et le QNAP
  dans le meme VLAN ou configurez le routage
