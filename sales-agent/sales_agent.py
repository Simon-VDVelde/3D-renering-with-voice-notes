#!/usr/bin/env python3
"""
sales_agent.py — Geautomatiseerde B2B Lead Generator & Outreach Agent
Voor de 3D Gaussian Splatting & Spraak-Annotatie Tool (Spatial SOP).

Functionaliteiten:
1. Bedrijven zoeken via Serper.dev API (Google Places / Maps / Search)
2. Homepagina & contactpagina's scrapen met BeautifulSoup (activiteiten & emailadres)
3. Automatisch een tijdelijke 3D demo-pagina & voorbeeldmodel genereren in onze eigen SQLite-database
4. OpenAI API aanroepen om een korte, hyper-gepersonaliseerde B2B sales e-mail te schrijven
   inclusief de unieke demo-link voor directe interactie door de prospect.
Resultaten worden direct geëxporteerd naar leads.csv (Excel-compatibel).
"""

import os
import re
import csv
import json
import time
import uuid
import sqlite3
import argparse
import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

# ==========================================================
# OMGEVINGSVARIABELEN INLADEN
# ==========================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
LOCAL_ENV = SCRIPT_DIR / ".env"
PARENT_ENV = PROJECT_ROOT / "tool" / ".env"

def load_environment():
    """Laadt API keys uit sales-agent/.env of tool/.env."""
    env_paths = [LOCAL_ENV, PARENT_ENV]
    for env_path in env_paths:
        if env_path.is_file():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k not in os.environ and v:
                                os.environ[k] = v
            except Exception:
                pass

load_environment()

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
DEFAULT_BASE_DEMO_URL = os.environ.get("BASE_DEMO_URL", "http://localhost:8080/demo").strip().rstrip("/")


# ==========================================================
# DEMO MANAGER: DATABASE & 3D MODEL DEMO-GENERATOR
# ==========================================================
class DemoManager:
    """
    Beheert de aanmaak van gepersonaliseerde, tijdelijke 3D demo's
    en registreert deze in de centrale SQLite database.
    """

    def __init__(self, base_url=None):
        self.project_root = PROJECT_ROOT
        self.demos_dir = self.project_root / "demos"
        self.demos_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.demos_dir / "demos.db"
        self.base_url = (base_url or DEFAULT_BASE_DEMO_URL).rstrip("/")
        self._init_db()

    def _init_db(self):
        """Initialiseert de SQLite database tabel voor demo's."""
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS demos (
                id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                website TEXT,
                email TEXT,
                sector TEXT,
                demo_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                annotations_json TEXT,
                views_count INTEGER DEFAULT 0,
                last_viewed_at TEXT,
                status TEXT DEFAULT 'active'
            );
        """)
        conn.commit()
        conn.close()

    def slugify(self, text):
        """Genereert een schone, URL-veilige slug van een bedrijfsnaam."""
        clean = re.sub(r'[^a-zA-Z0-9]+', '-', text.lower()).strip('-')
        return clean or f"demo-{int(time.time())}"

    def generate_tailored_annotations(self, company_name, sector, company_summary):
        """
        Genereert realistische, sectorspecifieke 3D inspectiepunten en instructies
        afgestemd op het type machines of installaties van het bedrijf.
        """
        combined = f"{sector} {company_summary}".lower()

        if any(w in combined for w in ["verpakking", "pack", "lijn", "folie", "doos"]):
            steps_data = [
                ("Invoer- & Doseersysteem", "Inspecteer de optische fotocellen en de doorvoerband op stabiele tray-aanvoer.", 11.2, [0.0157, -1.0119, 2.3074]),
                ("Sealbalk & Verwarmingselement", "Verifieer de sealtemperatuur (180°C) en reinig eventuele folieresten van de teflon-strips.", 28.5, [-0.4210, -0.7850, 2.1500]),
                ("Noodstop & Servobesturing", "Test de veiligheidsafscherming en controleer de storingscode op de frequentieregelaar.", 47.0, [0.4850, -0.6200, 2.4100])
            ]
        elif any(w in combined for w in ["robot", "automat", "flow", "plc", "vision"]):
            steps_data = [
                ("Robotarm Home-Positie", "Verifieer de nulpuntskalibratie van assen 1 t/m 6 vóór vrijgave van de automatische cyclus.", 14.0, [0.0157, -1.0119, 2.3074]),
                ("Pneumatische Grijper & Vacuüm", "Controleer de voedingsdruk (min. 6.2 bar) en reinig de vacuümzuignappen.", 32.4, [-0.4210, -0.7850, 2.1500]),
                ("Veiligheidslichtscherm", "Test het optische muting-systeem en controleer of de machine direct in noodstop valt.", 51.8, [0.4850, -0.6200, 2.4100])
            ]
        elif any(w in combined for w in ["koel", "hvac", "pomp", "airco", "vries"]):
            steps_data = [
                ("Compressor Drukniveaus", "Controleer de zuig- en persdrukmanometers conform de koudemiddeltabel van de installatie.", 12.8, [0.0157, -1.0119, 2.3074]),
                ("Condensor & Ventilatormotor", "Inspecteer de aluminium lamellen op vervuiling en controleer op trillingen in de motorlagers.", 30.1, [-0.4210, -0.7850, 2.1500]),
                ("Expansieventiel & Lekdetectie", "Voer een lekcontrole uit op de soldeerverbindingen en kranen van het koelcircuit.", 49.3, [0.4850, -0.6200, 2.4100])
            ]
        elif any(w in combined for w in ["elektro", "bord", "schakel", "kast", "paneel"]):
            steps_data = [
                ("Hoofdschakelaar & LOTO Procedure", "Vergrendel de hoofdschakelaar spanningsvrij volgens de industriële LOTO-norm.", 10.5, [0.0157, -1.0119, 2.3074]),
                ("Voeding & PLC Modules", "Controleer de 24V DC busspanning en verifieer de status-LED's op de communicatiekaarten.", 29.0, [-0.4210, -0.7850, 2.1500]),
                ("Klemmenstrook Thermografie", "Inspecteer met de infraroodsensor op abnormale overgangsweerstanden of warmteontwikkeling.", 48.2, [0.4850, -0.6200, 2.4100])
            ]
        else:
            steps_data = [
                ("Startcyclus & Hoofdcomponenten", "Controleer de mechanische uitlijning en zorg dat alle borgbouten op koppel zijn aangedraaid.", 12.0, [0.0157, -1.0119, 2.3074]),
                ("Smeerpunten & Geleidingen", "Breng lithiumvet aan op de centrale smeerpunten en inspecteer op axiale speling.", 29.5, [-0.4210, -0.7850, 2.1500]),
                ("Veiligheidsafscherming & Inspectie", "Controleer de deurschakelaars en verifieer de noodstopknop vóór inschakeling.", 48.0, [0.4850, -0.6200, 2.4100])
            ]

        annotations = []
        for idx, (title, desc, ts, pos) in enumerate(steps_data, 1):
            annotations.append({
                "step": idx,
                "title": title,
                "description": desc,
                "timestamp": ts,
                "matched_frame": "frames/frame_0162.jpg",
                "debug_snapshot": "debug_frames/step_01_0162.jpg",
                "translations": {
                    "nl": {"part_name": title, "instruction": desc},
                    "en": {"part_name": title, "instruction": desc}
                },
                "pixel_uv": [982, 1635],
                "position_3d": pos,
                "camera_position_3d": [pos[0] + 0.03, pos[1] + 0.32, pos[2] - 3.44]
            })

        return {
            "metadata": {
                "organization": f"{company_name} — 3D Demo Preview",
                "confidentiality": "Gepersonaliseerde Demonstratie — Spatial SOP",
                "version": "1.0",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "total_steps": len(annotations)
            },
            "annotations": annotations
        }

    def create_company_demo(self, company_name, website="", email="", sector="", company_summary="", validity_days=30):
        """
        Maakt een unieke demo-pagina, bestanden en database-record aan voor een prospect.
        Geeft een direct klikbare link terug (bijv. https://jouwwebsite.be/demo/bedrijfsnaam).
        """
        slug = self.slugify(company_name)
        demo_id = f"demo_{uuid.uuid4().hex[:8]}"
        now = datetime.datetime.now(datetime.timezone.utc)
        expires = now + datetime.timedelta(days=validity_days)

        created_at_str = now.strftime("%Y-%m-%d %H:%M:%S")
        expires_at_str = expires.strftime("%Y-%m-%d %H:%M:%S")
        expiry_display = expires.strftime("%d-%m-%Y")

        demo_dir = self.demos_dir / slug
        demo_dir.mkdir(parents=True, exist_ok=True)

        # 1. Annotaties met 3D-coördinaten en gesproken instructies wegschrijven
        annotations_data = self.generate_tailored_annotations(company_name, sector, company_summary)
        with open(demo_dir / "annotations.json", "w", encoding="utf-8") as f:
            json.dump(annotations_data, f, indent=2, ensure_ascii=False)

        # 2. Configbestand opslaan (pin_enabled=False zodat de prospect direct zonder drempels kan kijken)
        config_data = {
            "pin_enabled": False,
            "is_demo": True,
            "default_role": "operator",
            "organization": f"{company_name} — 3D Demo Preview",
            "confidentiality": f"Tijdelijke Demo • Geldig tot {expiry_display}",
            "expires_at": expires.isoformat(),
            "company_name": company_name,
            "company_website": website
        }
        with open(demo_dir / "config.json", "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        # 3. Unieke demo-link opstellen
        demo_url = f"{self.base_url}/{slug}"

        # 4. Registreren in SQLite database (Upsert)
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO demos (id, company_name, slug, website, email, sector, demo_url, created_at, expires_at, annotations_json, views_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'active')
            ON CONFLICT(slug) DO UPDATE SET
                company_name=excluded.company_name,
                website=excluded.website,
                email=excluded.email,
                sector=excluded.sector,
                demo_url=excluded.demo_url,
                created_at=excluded.created_at,
                expires_at=excluded.expires_at,
                annotations_json=excluded.annotations_json,
                status='active';
        """, (
            demo_id,
            company_name,
            slug,
            website,
            email,
            sector,
            demo_url,
            created_at_str,
            expires_at_str,
            json.dumps(annotations_data)
        ))
        conn.commit()
        conn.close()

        print(f"   ✨ [DemoManager] Tijdelijk 3D demo-model aangemaakt in database:")
        print(f"      🔗 Link: {demo_url} (Geldig tot {expiry_display})")

        return {
            "demo_id": demo_id,
            "slug": slug,
            "demo_url": demo_url,
            "expires_at": expiry_display
        }


# ==========================================================
# MODULE 1: SERPER.DEV SEARCH CLIENT (Google Places / Search)
# ==========================================================
class SerperSearcher:
    """Zoekt doelgerichte B2B bedrijven via de Serper.dev API."""

    def __init__(self, api_key=None):
        self.api_key = api_key or SERPER_API_KEY
        self.places_url = "https://google.serper.dev/places"
        self.search_url = "https://google.serper.dev/search"

    def search_companies(self, query="machinebouwers Vlaanderen", max_results=15, country="be"):
        """Zoekt bedrijven en haalt naam, website, telefoon en adres op."""
        if not self.api_key:
            print("⚠️ Geen SERPER_API_KEY gevonden in sales-agent/.env.")
            print("💡 We schakelen over naar de ingebouwde demodataset met echte machinebouw-KMO's...")
            return self._get_fallback_leads(max_results)

        print(f"\n🔎 [Module 1] Zoeken naar bedrijven via Serper.dev voor: '{query}' (Land: {country})...")
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "q": query,
            "gl": country,
            "hl": "nl",
            "num": max_results
        }

        try:
            res = requests.post(self.places_url, headers=headers, json=payload, timeout=15)
            leads = []

            if res.status_code == 200:
                data = res.json()
                places = data.get("places", [])
                print(f"   ✓ {len(places)} bedrijven gevonden via Google Places!")

                for item in places:
                    website = item.get("website", "")
                    if website:
                        leads.append({
                            "name": item.get("title") or item.get("name", "Onbekend bedrijf"),
                            "website": website,
                            "phone": item.get("phoneNumber", ""),
                            "address": item.get("address", ""),
                            "category": item.get("category", "Industrie / Techniek")
                        })
            else:
                print(f"   ⚠️ Places API status {res.status_code}, probeer web search fallback...")
                res_search = requests.post(self.search_url, headers=headers, json=payload, timeout=15)
                if res_search.status_code == 200:
                    organic = res_search.json().get("organic", [])
                    for item in organic:
                        link = item.get("link", "")
                        domain = urlparse(link).netloc
                        if domain and not any(ex in domain for ex in ["linkedin", "facebook", "wikipedia", "goudengids"]):
                            leads.append({
                                "name": item.get("title", "").split("-")[0].split("|")[0].strip(),
                                "website": link,
                                "phone": "",
                                "address": country.upper(),
                                "category": query
                            })

            if not leads:
                print("   ℹ️ Geen directe resultaten met website, fallback naar demodataset...")
                return self._get_fallback_leads(max_results)

            return leads[:max_results]

        except Exception as e:
            print(f"   ❌ Fout bij Serper.dev API: {e}")
            return self._get_fallback_leads(max_results)

    def _get_fallback_leads(self, count):
        """Curated lijst van machinebouwers en industriële installateurs voor demonstratie."""
        sample = [
            {"name": "PackSys Machinebouw", "website": "https://www.packsys.be", "phone": "+32 56 12 34 56", "address": "Kortrijk, België", "category": "Speciaalmachinebouw & Verpakking"},
            {"name": "RoboFlow Automation", "website": "https://www.roboflow.be", "phone": "+32 9 234 56 78", "address": "Gent, België", "category": "Industriële Automatisering & Robotica"},
            {"name": "VanderBilt Koeltechniek", "website": "https://www.vanderbilt-koeling.be", "phone": "+32 3 456 78 90", "address": "Antwerpen, België", "category": "Industriële HVAC & Koelgroepen"},
            {"name": "HydroDrive Hydrauliek", "website": "https://www.hydrodrive-service.be", "phone": "+32 50 78 90 12", "address": "Brugge, België", "category": "Pompen & Hydraulische Installaties"},
            {"name": "ElectroPanel Bordenbouw", "website": "https://www.electropanel.be", "phone": "+32 53 88 11 22", "address": "Aalst, België", "category": "Industriële Schakelkasten"},
            {"name": "DeltaTech Machine Constructie", "website": "https://www.deltatech-machines.nl", "phone": "+31 40 234 5678", "address": "Eindhoven, Nederland", "category": "Transportbanden & Assemblage"},
            {"name": "FoodMech Procesinstallaties", "website": "https://www.foodmech.be", "phone": "+32 51 22 33 44", "address": "Roeselare, België", "category": "Voedingsmiddelen Machinebouw"},
            {"name": "TransCon Conveyor Systems", "website": "https://www.transcon-belgium.be", "phone": "+32 89 30 40 50", "address": "Genk, België", "category": "Interne Logistiek & Rollenbanen"}
        ]
        return sample[:count]


# ==========================================================
# MODULE 2: WEBSITE SCRAPER (BeautifulSoup)
# ==========================================================
class WebsiteScraper:
    """Scrapet bedrijfswebsites om kernactiviteiten en contactadressen te extraheren."""

    def __init__(self, timeout=10):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        self.email_regex = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

    def clean_url(self, url):
        """Zorgt voor een geldige HTTP/HTTPS URL."""
        if not url:
            return ""
        url = url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        return url

    def extract_emails(self, text, soup=None):
        """Vindt emailadressen via mailto: links en regex."""
        emails = set()

        if soup:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("mailto:"):
                    em = href.replace("mailto:", "").split("?")[0].strip()
                    if self.email_regex.match(em):
                        emails.add(em.lower())

        for match in self.email_regex.findall(text):
            em = match.lower()
            if not any(em.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".js", ".css"]):
                if not any(fake in em for fake in ["example.com", "domain.com", "sentry", "wixpress", "bootstrap"]):
                    emails.add(em)

        def email_priority(e):
            if e.startswith("info@"): return 0
            if e.startswith("contact@"): return 1
            if e.startswith("sales@"): return 2
            if e.startswith("service@"): return 3
            return 4

        sorted_emails = sorted(list(emails), key=email_priority)
        return sorted_emails[0] if sorted_emails else ""

    def scrape_company_profile(self, url):
        """Scrapet de homepage en eventuele contactpagina."""
        url = self.clean_url(url)
        if not url:
            return {"summary": "Geen website beschikbaar", "email": ""}

        print(f"   🌐 [Module 2] Scrapen van {url}...")
        try:
            res = requests.get(url, headers=self.headers, timeout=self.timeout, verify=False)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")

            for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
                tag.decompose()

            meta_desc = ""
            meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            if meta_tag and meta_tag.get("content"):
                meta_desc = meta_tag["content"].strip()

            page_title = soup.title.string.strip() if soup.title and soup.title.string else ""
            h1_texts = [h.get_text().strip() for h in soup.find_all(["h1", "h2"]) if h.get_text().strip()]

            body_text = soup.get_text(separator=" ", strip=True)
            body_clean = re.sub(r"\s+", " ", body_text)

            email = self.extract_emails(body_clean, soup)

            if not email:
                for a in soup.find_all("a", href=True):
                    href = a["href"].lower()
                    if any(term in href for term in ["contact", "over-ons", "contacteer"]):
                        contact_url = urljoin(url, a["href"])
                        try:
                            c_res = requests.get(contact_url, headers=self.headers, timeout=6, verify=False)
                            if c_res.status_code == 200:
                                c_soup = BeautifulSoup(c_res.text, "html.parser")
                                email = self.extract_emails(c_soup.get_text(), c_soup)
                                if email:
                                    break
                        except Exception:
                            pass

            summary_parts = []
            if page_title: summary_parts.append(f"Titel: {page_title}")
            if meta_desc: summary_parts.append(f"Omschrijving: {meta_desc}")
            if h1_texts: summary_parts.append(f"Kernactiviteiten: {', '.join(h1_texts[:4])}")
            snippet = body_clean[:400]
            summary_parts.append(f"Website fragment: {snippet}")

            return {
                "summary": " | ".join(summary_parts),
                "email": email or "info@" + urlparse(url).netloc.replace("www.", "")
            }

        except Exception as e:
            domain = urlparse(url).netloc.replace("www.", "")
            return {
                "summary": f"KMO actief in machinebouw of technische installaties ({domain})",
                "email": f"info@{domain}" if domain else ""
            }


# ==========================================================
# MODULE 3: OPENAI B2B SALES EMAIL GENERATOR
# ==========================================================
class SalesEmailGenerator:
    """Schrijft hyper-gepersonaliseerde B2B sales e-mails inclusief de unieke demo-link."""

    def __init__(self, api_key=None, model="gpt-4o-mini"):
        self.api_key = api_key or OPENAI_API_KEY
        self.model = model
        self.client = None
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except Exception as e:
                print(f"⚠️ OpenAI client fout: {e}")

    def generate_email(self, company_name, company_summary, category, demo_url):
        """Genereert een korte e-mail met verplichte vermelding van de interactieve 3D demo-link."""
        if not self.client:
            return self._generate_template_email(company_name, category, demo_url)

        system_prompt = f"""Je bent een sympathieke, deskundige B2B Business Developer in Vlaanderen/Nederland.
Je verkoopt 'Spatial SOP': software die een gewone smartphonevideo van een machine omzet in een interactief 3D digital twin model, waarbij wat de monteur hardop vertelt automatisch als 3D tekstpins op de exacte componenten van het toestel wordt geplaatst.

DOEL: Schrijf een korte, gepersonaliseerde koude e-mail naar dit bedrijf.

REGELS:
1. Maximaal 110-140 woorden. To the point, professioneel, geen overdreven marketing-clichés.
2. Open met een concrete verwijzing naar hun machines, installaties of projecten (gebaseerd op hun website-samenvatting).
3. Leg het pijnpunt uit: Papieren handleidingen en dikke PDF's worden niet gelezen; complexe machines leiden tot fouten en onnodige telefoontjes naar service.
4. Onze oplossing: 1 minuut filmen met smartphone + spraak -> interactieve 3D handleiding met gesproken pins + QR-sticker op de machine.
5. VERPLICHTE DEMO-LINK: We hebben speciaal voor dit bedrijf alvast een werkend 3D-voorbeeld klaargezet. Je MOET de unieke link ({demo_url}) expliciet in de mail vermelden en hen uitnodigen om dit direct op mobiel of laptop te openen (zonder installatie of inlog).
6. Laagdrempelige Call to Action (CTA): Vraag of ze openstaan voor een korte online kennismaking van 10 minuten.
7. Toon: Vriendelijk, modern zakelijk Nederlands.
8. Output ALTIJD in JSON formaat met exact twee velden: 'subject' en 'body'."""

        user_prompt = f"""Bedrijfsnaam: {company_name}
Sector/Specialisatie: {category}
Gescrapete website info: {company_summary}
Unieke 3D demo link: {demo_url}

Schrijf nu een gepersonaliseerd onderwerp en de e-mailtekst met de demo-link."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.7
            )
            data = json.loads(response.choices[0].message.content)
            subject = data.get("subject", "")
            body = data.get("body", "")

            # Veiligheidscheck: zorg dat de demo link altijd in de body staat
            if demo_url not in body:
                body += f"\n\nBekijk hier alvast het interactieve 3D-voorbeeld voor {company_name}:\n👉 {demo_url}"

            return subject, body

        except Exception as e:
            print(f"   ⚠️ OpenAI generatie mislukt ({e}), fallback naar template...")
            return self._generate_template_email(company_name, category, demo_url)

    def _generate_template_email(self, company_name, category, demo_url):
        """Hoogwaardige template e-mail inclusief unieke demo-link."""
        subject = f"3D-instructies & interactieve preview voor de installaties van {company_name}"
        body = f"""Beste team {company_name},

Met veel interesse bekeek ik jullie projecten in {category.lower()}. Jullie ontwerpen en bouwen technisch hoogwaardige installaties waarbij correcte bediening en vlekkeloos onderhoud cruciaal zijn.

In de praktijk zien we dat traditionele handleidingen en dikke PDF's vaak in een kast belanden, waardoor klanten of technici blijven bellen bij storingen of onderhoud.

Met onze software zetten we een smartphonevideo van een installatie binnen enkele minuten om in een interactieve 3D digital twin. Terwijl een technicus filmt en instructies inspreekt, plaatst onze AI deze gesproken toelichting automatisch als klikbare 3D-markers op de juiste componenten van de machine. Monteurs scannen op locatie simpelweg een QR-sticker op het toestel.

Om te laten zien hoe dit werkt, hebben we alvast een interactieve 3D-voorbeeldpagina klaargezet voor {company_name}:
👉 {demo_url}
(Direct klikbaar in uw browser op smartphone of laptop — zonder inlog of installatie).

Zou u openstaan voor een korte kennismaking van 10 minuten om te zien hoe dit jullie inspecties of opleveringen kan versnellen?

Met vriendelijke groet,

Simon
Spatial SOP — 3D Werkinstructies"""
        return subject, body


# ==========================================================
# ORCHESTRATOR & CSV EXPORT
# ==========================================================
def run_sales_agent(query="machinebouwers Vlaanderen", count=10, country="be", output_file="leads.csv", demo=False, base_url=None):
    """
    Orkestreert de complete flow:
    Zoeken -> Scrapen -> 3D Demo Aanmaken in Database -> AI Copywriting met Demo Link -> CSV Export.
    """
    effective_base_url = (base_url or DEFAULT_BASE_DEMO_URL).rstrip("/")

    print("==========================================================")
    print("🚀 B2B SALES AGENT — LEAD GENERATION & AI OUTREACH")
    print("==========================================================")
    print(f"🎯 Zoekopdracht:  {query}")
    print(f"📊 Aantal leads:   {count}")
    print(f"🌐 Demo Base URL:  {effective_base_url}")
    print(f"📁 Uitvoerbestand: {output_file}")
    print("==========================================================")

    searcher = SerperSearcher()
    scraper = WebsiteScraper()
    demo_manager = DemoManager(base_url=effective_base_url)
    copywriter = SalesEmailGenerator()

    # 1. Bedrijven zoeken via Serper.dev
    if demo:
        raw_leads = searcher._get_fallback_leads(count)
    else:
        raw_leads = searcher.search_companies(query=query, max_results=count, country=country)

    if not raw_leads:
        print("❌ Geen leads gevonden. Controleer zoekopdracht of API-sleutel.")
        return

    processed_leads = []

    # 2, 3 & 4. Scrapen, Demo Genereren en e-mails schrijven
    for idx, lead in enumerate(raw_leads, 1):
        name = lead.get("name", "Bedrijf")
        website = lead.get("website", "")
        phone = lead.get("phone", "")
        address = lead.get("address", "")
        category = lead.get("category", query)

        print(f"\n[{idx}/{len(raw_leads)}] Verwerken: {name} ({website})")

        # Module 2: Scrape website profiel & e-mail
        scrape_result = scraper.scrape_company_profile(website)
        company_summary = scrape_result.get("summary", "")
        email = scrape_result.get("email", "")

        # Nieuw: Automatisch een tijdelijke 3D demo aanmaken in onze database
        demo_info = demo_manager.create_company_demo(
            company_name=name,
            website=website,
            email=email,
            sector=category,
            company_summary=company_summary,
            validity_days=30
        )
        demo_url = demo_info["demo_url"]
        expiry_date = demo_info["expires_at"]

        # Module 3: OpenAI e-mail genereren met de unieke demo-link
        print("   ✍️ [Module 3] Gepersonaliseerde salesmail genereren via OpenAI...")
        subject, email_body = copywriter.generate_email(name, company_summary, category, demo_url)

        processed_leads.append({
            "Bedrijfsnaam": name,
            "Website": website,
            "Email": email,
            "Telefoon": phone,
            "Locatie": address,
            "Sector": category,
            "Demo_Link": demo_url,
            "Geldig_Tot": expiry_date,
            "Bedrijfsomschrijving": company_summary[:250] + "..." if len(company_summary) > 250 else company_summary,
            "Onderwerp_Mail": subject,
            "Gepersonaliseerde_Mail": email_body,
            "Status": "Klaar voor verzending"
        })

        time.sleep(0.5)

    # Opslaan naar CSV met UTF-8 BOM voor probleemloos openen in Excel
    out_path = Path(output_file)
    if not out_path.is_absolute():
        out_path = SCRIPT_DIR / output_file

    fieldnames = [
        "Bedrijfsnaam",
        "Website",
        "Email",
        "Telefoon",
        "Locatie",
        "Sector",
        "Demo_Link",
        "Geldig_Tot",
        "Bedrijfsomschrijving",
        "Onderwerp_Mail",
        "Gepersonaliseerde_Mail",
        "Status"
    ]

    with open(out_path, "w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for item in processed_leads:
            writer.writerow(item)

    print("\n==========================================================")
    print(f"🎉 SUCCES! {len(processed_leads)} leads met unieke 3D-demo's opgeslagen:")
    print(f"👉 CSV Bestand: {out_path}")
    print(f"📂 Database:    {demo_manager.db_path}")
    print("==========================================================")


def main():
    parser = argparse.ArgumentParser(description="B2B Sales Agent voor 3D Gaussian Splatting & Spraak-Annotatie Tool.")
    parser.add_argument("--query", type=str, default="machinebouwers Vlaanderen", help="Zoekterm voor Serper.dev")
    parser.add_argument("--count", type=int, default=10, help="Aantal leads om te verzamelen (standaard: 10)")
    parser.add_argument("--country", type=str, default="be", help="Landcode (bijv. 'be' voor België, 'nl' voor Nederland)")
    parser.add_argument("--output", type=str, default="leads.csv", help="Naam van het CSV-uitvoerbestand (standaard: leads.csv)")
    parser.add_argument("--demo", action="store_true", help="Draai met voorbeeld-leads zonder Serper.dev API-aanroepen")
    parser.add_argument("--base-url", type=str, default=None, help="Basis-URL voor gegenereerde demo-links (bijv. 'https://jouwwebsite.be/demo')")

    args = parser.parse_args()
    run_sales_agent(
        query=args.query,
        count=args.count,
        country=args.country,
        output_file=args.output,
        demo=args.demo,
        base_url=args.base_url
    )

if __name__ == "__main__":
    main()
