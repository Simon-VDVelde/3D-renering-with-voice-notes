# 3D Rendering with Voice Notes & Spatial SOP 🚀

Zet smartphone-video's met gesproken toelichting volautomatisch om in interactieve **3D Gaussian Splatting** digital twins met AI-gekoppelde 3D annotatie-pins. 

Ideaal voor machinebouwers, installateurs en technische inspecteurs: technici scannen simpelweg een QR-sticker op de fysieke machine en zien direct een interactieve 3D-werkinstructie (SOP) op hun smartphone of tablet.

---

## 🌟 Belangrijkste Functionaliteiten

1. **Smartphone Video & Audio Reconstructie**:
   - Geen dure lidar-scanners nodig: een gewone smartphone-video rondom het toestel volstaat.
   - 3D Gaussian Splatting (Brush engine / COLMAP) voor fotorealistische, ruimtelijke weergave.

2. **Spraak-naar-3D Hotspots**:
   - Gesproken uitleg tijdens het filmen wordt automatisch getranscribeerd met timestamps.
   - AI detecteert welke machine-onderdelen besproken worden en koppelt deze aan de exacte 3D-coördinaten op de machine.

3. **Web 3D Viewer & Human-in-the-Loop Editor**:
   - Lichtgewicht mobiele 3D viewer (geen app-installatie nodig).
   - **Operator modus (PIN beveiligd)**: Stap-voor-stap werkinstructies met automatische camerazoom naar elk punt.
   - **Beheerders / Editor modus**: Verplaats pins met realtime X, Y, Z micro-nudges (+/- 2 cm), 360° vrije orbit-rotatie en directe tekstbewerking.

4. **Ingebouwde B2B Lead Generator (`/sales-agent`)**:
   - Module 1: Automatisch relevante bedrijven (machinebouwers, automatisering, installateurs) opzoeken via de Serper.dev Google Maps API.
   - Module 2: Homepages en contactpagina's scrapen via BeautifulSoup om specialisaties en contactmails (`info@`, `contact@`) te vinden.
   - Module 3: Gepersonaliseerde koude sales-e-mails genereren via OpenAI en direct exporteren naar `leads.csv`.

---

## 📂 Projectstructuur

```text
├── tool/                    # Core pipeline & Webportaal
│   ├── build_sop.sh         # Pipeline orchestratiescript (video -> COLMAP -> Splat -> AI pins)
│   ├── server.py            # Localhost portaal & REST API voor projectbeheer
│   ├── transcribe.py        # Spraaktranscriptie module
│   ├── build_annotations.py # AI visie & 3D coördinaten koppeling
│   ├── lidar_detector.py    # Diepte- en point cloud analyse
│   ├── make_transforms.py   # Camera poses en transforms
│   ├── viewer/              # Vite / Three.js 3D Web Viewer & Editor broncode
│   └── web/                 # Dashboard web UI
├── sales-agent/             # B2B Lead Generatie & AI Outreach Agent
│   ├── sales_agent.py       # 3 modules: Serper API + Scraper + OpenAI mail generator
│   ├── requirements.txt     # Python packages voor de sales agent
│   └── .env.example         # Template voor Serper & OpenAI API keys
├── run_portal.sh            # Eén-klik opstartscript voor het lokale beheerportaal
├── .gitignore               # Negeert zware 3D/video data, node_modules en secrets
└── README.md
```

---

## 🚀 Snelle Start

### 1. Vereisten
- Python 3.10+ met virtual environment
- Node.js 18+ & npm
- FFmpeg & COLMAP (voor het lokaal draaien van de volledige reconstructie-pipeline)

### 2. Installatie

```bash
# Clone het project
git clone https://github.com/Simon-VDVelde/3D-renering-with-voice-notes.git
cd 3D-renering-with-voice-notes

# Python virtuele omgeving opzetten
python3 -m venv tool/.venv
source tool/.venv/bin/activate
pip install -r sales-agent/requirements.txt

# Viewer dependencies installeren en builden
cd tool/viewer
npm install
npm run build
cd ../..
```

### 3. Configuratie (.env)

Kopieer de voorbeeldconfiguraties en voeg je gewenste API keys toe:

```bash
cp tool/.env.example tool/.env
cp sales-agent/.env.example sales-agent/.env
```

### 4. Het Beheerportaal starten

Start het dashboard en de webserver met:
```bash
./run_portal.sh
```
Open vervolgens in je browser: [http://localhost:8000](http://localhost:8000)

### 5. De B2B Sales Agent draaien

Genereer eenvoudig gekwalificeerde B2B-leads en gepersonaliseerde e-mails:
```bash
# Zoek bijvoorbeeld 20 machinebouwers in Vlaanderen:
python3 sales-agent/sales_agent.py --query "machinebouwers Vlaanderen" --count 20

# Bekijk de resultaten:
# De leads worden direct opgeslagen in sales-agent/leads.csv
```

---

## 🔒 Veiligheid & Privacy

- `.env` bestanden met API keys en wachtwoorden worden via `.gitignore` **nooit** gecommit naar GitHub.
- Zware 3D point clouds (`.ply`, `.splat`), videobestanden (`.mp4`) en trainingsmappen worden lokaal bewaard en niet meegepusht.
