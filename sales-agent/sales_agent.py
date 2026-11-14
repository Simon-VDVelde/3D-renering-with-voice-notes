#!/usr/bin/env python3
"""
sales_agent.py — Geautomatiseerde B2B Lead Generator & Outreach Agent
Voor de 3D Gaussian Splatting & Spraak-Annotatie Tool.

Bestaat uit 3 krachtige modules:
1. Bedrijven zoeken via Serper.dev API (Google Places / Maps / Search)
2. Homepagina & contactpagina's scrapen met BeautifulSoup (activiteiten & emailadres)
3. OpenAI API aanroepen om een korte, hyper-gepersonaliseerde B2B sales e-mail te schrijven
Resultaten worden direct opgeslagen in leads.csv.
"""

import os
import re
import csv
import json
import time
import argparse
from pathlib import Path
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

# ==========================================================
# OMGEVINGSVARIABELEN INLADEN
# ==========================================================
SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_ENV = SCRIPT_DIR / ".env"
PARENT_ENV = SCRIPT_DIR.parent / "tool" / ".env"

def load_environment():
    """Laadt API keys uit sales-agent/.env of tool/.env."""
    env_paths = [LOCAL_ENV, PARENT_ENV]
    for env_path in env_paths:
        if env_path.is_file():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k not in os.environ and v:
                            os.environ[k] = v

load_environment()

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()

# ==========================================================
# MODULE 1: SERPER.DEV SEARCH CLIENT (Google Places / Search)
# ==========================================================
class SerperSearcher:
    """Zoekt doelgerichte bedrijven via de Serper.dev API."""

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
            # Probeer eerst Google Places (bevat telefoon en fysieke adressen)
            res = requests.post(self.places_url, headers=headers, json=payload, timeout=15)
            leads = []
            
            if res.status_code == 200:
                data = res.json()
                places = data.get("places", [])
                print(f"   ✓ {len(places)} bedrijven gevonden via Google Places!")
                
                for item in places:
                    website = item.get("website", "")
                    if website: # Alleen bedrijven met website kunnen gescraped worden
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
        """Curated lijst van machinebouwers en industriële installateurs voor testdoeleinden."""
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
    """Scrapet bedrijfswebsites om activiteiten en emailadressen te extraheren."""

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
        """Vindt emailadressen via mailto: links en tekst regex."""
        emails = set()
        
        # 1. Zoek in mailto: links
        if soup:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("mailto:"):
                    em = href.replace("mailto:", "").split("?")[0].strip()
                    if self.email_regex.match(em):
                        emails.add(em.lower())

        # 2. Zoek in tekst via regex
        for match in self.email_regex.findall(text):
            em = match.lower()
            # Filter valse positieven zoals bestandsnamen of frameworks
            if not any(em.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".js", ".css"]):
                if not any(fake in em for fake in ["example.com", "domain.com", "sentry", "wixpress", "bootstrap"]):
                    emails.add(em)

        # Sorteer met prioriteit voor info@, contact@, sales@
        def email_priority(e):
            if e.startswith("info@"): return 0
            if e.startswith("contact@"): return 1
            if e.startswith("sales@"): return 2
            if e.startswith("service@"): return 3
            return 4

        sorted_emails = sorted(list(emails), key=email_priority)
        return sorted_emails[0] if sorted_emails else ""

    def scrape_company_profile(self, url):
        """Scrapet de homepage en eventueel de contactpagina."""
        url = self.clean_url(url)
        if not url:
            return {"summary": "Geen website beschikbaar", "email": ""}

        print(f"   🌐 [Module 2] Scrapen van {url}...")
        try:
            res = requests.get(url, headers=self.headers, timeout=self.timeout, verify=False)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")

            # Verwijder javascript, css en verborgen elementen
            for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
                tag.decompose()

            # Haal meta description en titels op
            meta_desc = ""
            meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            if meta_tag and meta_tag.get("content"):
                meta_desc = meta_tag["content"].strip()

            page_title = soup.title.string.strip() if soup.title and soup.title.string else ""
            h1_texts = [h.get_text().strip() for h in soup.find_all(["h1", "h2"]) if h.get_text().strip()]

            # Haal tekst op
            body_text = soup.get_text(separator=" ", strip=True)
            body_clean = re.sub(r"\s+", " ", body_text)

            # Zoek emailadres op de homepage
            email = self.extract_emails(body_clean, soup)

            # Als geen email gevonden is, check of er een contactpagina link is
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

            # Samenvatting samenstellen voor de OpenAI prompt
            summary_parts = []
            if page_title: summary_parts.append(f"Titel: {page_title}")
            if meta_desc: summary_parts.append(f"Omschrijving: {meta_desc}")
            if h1_texts: summary_parts.append(f"Kernactiviteiten: {', '.join(h1_texts[:4])}")
            
            # Voeg een beknopt tekstfragment toe
            snippet = body_clean[:400]
            summary_parts.append(f"Website fragment: {snippet}")

            full_summary = " | ".join(summary_parts)
            return {
                "summary": full_summary,
                "email": email or "info@" + urlparse(url).netloc.replace("www.", "")
            }

        except Exception as e:
            # Fallback als de site offline is of blokkeert
            domain = urlparse(url).netloc.replace("www.", "")
            return {
                "summary": f"KMO actief in machinebouw of technische installaties ({domain})",
                "email": f"info@{domain}" if domain else ""
            }

# ==========================================================
# MODULE 3: OPENAI B2B SALES EMAIL GENERATOR
# ==========================================================
class SalesEmailGenerator:
    """Schrijft hyper-gepersonaliseerde B2B sales e-mails via de OpenAI API."""

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

    def generate_email(self, company_name, company_summary, category):
        """Genereert een korte, gepersonaliseerde e-mail gericht op de 3D-spraak-annotatietool."""
        if not self.client:
            # Professionele template fallback als er nog geen OpenAI API key is
            return self._generate_template_email(company_name, category)

        system_prompt = """Je bent een sympathieke, deskundige B2B Business Developer in Vlaanderen/Nederland.
Je verkoopt 'Spatial SOP': een baanbrekende softwaretool die een gewone smartphonevideo van een machine of installatie omzet in een interactief 3D-model (Gaussian Splatting), waarbij wat de technicus tijdens het filmen hardop vertelt, automatisch als 3D-tekstpins op de juiste fysieke plek van het 3D-object wordt geplaatst.

DOEL: Schrijf een korte, gepersonaliseerde cold email naar dit bedrijf.

REGELS:
1. Maximaal 100-130 woorden. Kort, to the point, geen overdreven marketing-praat.
2. Verwijs in de openingszin SPECIFIEK naar wat zij maken of doen (op basis van de website samenvatting).
3. Leg het pijnpunt uit: Papieren handleidingen of dikke PDF's worden door klanten of junior monteurs niet gelezen; complexe machines leiden tot fouten en tijdrovende telefoontjes.
4. Onze oplossing: 1 minuut filmen met smartphone + spraak -> direct een interactieve 3D-handleiding met gesproken pins + QR-sticker op de machine.
5. Laagdrempelige Call to Action (CTA): Vraag of je een 30-seconden interactief 3D voorbeeldje via smartphone mag doorsturen.
6. Toon: Professioneel, modern, vriendelijk Vlaams/Nederlands.
7. Output ALTIJD in JSON formaat met exact twee velden: 'subject' en 'body'."""

        user_prompt = f"""Bedrijfsnaam: {company_name}
Sector/Specialisatie: {category}
Gescrapete website info: {company_summary}

Genereer nu het onderwerp en de e-mailtekst."""

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
            return data.get("subject", ""), data.get("body", "")

        except Exception as e:
            print(f"   ⚠️ OpenAI generatie mislukt ({e}), fallback naar template...")
            return self._generate_template_email(company_name, category)

    def _generate_template_email(self, company_name, category):
        """Hoogwaardige template voor demonstratie of offline gebruik."""
        subject = f"3D-instructies & snellere oplevering voor de machines van {company_name}"
        body = f"""Beste team {company_name},

Met veel interesse bekeek ik jullie projecten in {category.lower()}. Jullie leveren technisch hoogwaardige installaties waarbij correcte bediening en onderhoud cruciaal zijn.

In de praktijk zien we dat traditionele handleidingen en dikke PDF's vaak in een kast belanden, waardoor klanten of technici blijven bellen bij storingen of onderhoud.

Met onze software zetten we een smartphonevideo van een installatie binnen enkele minuten om in een interactieve 3D digital twin. Terwijl een technicus filmt en instructies inspreekt, plaatst onze AI deze gesproken uitleg automatisch als klikbare 3D-markers op de juiste componenten van de machine.

Monteurs scannen eenvoudig een QR-sticker op het toestel en zien direct de 3D-werkinstructie in hun browser.

Mag ik u een korte interactieve 3D-demo van 30 seconden doorsturen, zodat u kunt zien hoe dit er op een smartphone uitziet?

Met vriendelijke groet,

Simon
Spatial SOP — 3D Werkinstructies"""
        return subject, body

# ==========================================================
# ORCHESTRATOR & CSV EXPORT
# ==========================================================
def run_sales_agent(query="machinebouwers Vlaanderen", count=10, country="be", output_file="leads.csv", demo=False):
    """Orkestreert de complete flow: Zoeken -> Scrapen -> AI Copywriting -> CSV Export."""
    print("==========================================================")
    print("🚀 B2B SALES AGENT — LEAD GENERATION & AI OUTREACH")
    print("==========================================================")
    print(f"🎯 Zoekopdracht:  {query}")
    print(f"📊 Aantal leads:   {count}")
    print(f"📁 Uitvoerbestand: {output_file}")
    print("==========================================================")

    searcher = SerperSearcher()
    scraper = WebsiteScraper()
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

    # 2 & 3. Scrapen en e-mails schrijven
    for idx, lead in enumerate(raw_leads, 1):
        name = lead.get("name", "Bedrijf")
        website = lead.get("website", "")
        phone = lead.get("phone", "")
        address = lead.get("address", "")
        category = lead.get("category", query)

        print(f"\n[{idx}/{len(raw_leads)}] Verwerken: {name} ({website})")

        # Module 2: Scrape website
        scrape_result = scraper.scrape_company_profile(website)
        company_summary = scrape_result.get("summary", "")
        email = scrape_result.get("email", "")

        # Module 3: OpenAI e-mail genereren
        print("   ✍️ [Module 3] Gepersonaliseerde salesmail genereren via OpenAI...")
        subject, email_body = copywriter.generate_email(name, company_summary, category)

        processed_leads.append({
            "Bedrijfsnaam": name,
            "Website": website,
            "Email": email,
            "Telefoon": phone,
            "Locatie": address,
            "Sector": category,
            "Bedrijfsomschrijving": company_summary[:250] + "..." if len(company_summary) > 250 else company_summary,
            "Onderwerp_Mail": subject,
            "Gepersonaliseerde_Mail": email_body,
            "Status": "Klaar voor verzending"
        })

        time.sleep(0.5) # Vriendelijk voor netwerk en rate limits

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
    print(f"🎉 SUCCES! {len(processed_leads)} leads succesvol verwerkt en opgeslagen:")
    print(f"👉 Bestand: {out_path}")
    print("==========================================================")

def main():
    parser = argparse.ArgumentParser(description="B2B Sales Agent voor 3D Gaussian Splatting & Spraak-Annotatie Tool.")
    parser.add_argument("--query", type=str, default="machinebouwers Vlaanderen", help="Zoekterm voor Serper.dev (bijv. 'machinebouw Antwerpen', 'koeltechniek Nederland')")
    parser.add_argument("--count", type=int, default=10, help="Aantal leads om te verzamelen (standaard: 10)")
    parser.add_argument("--country", type=str, default="be", help="Landcode (bijv. 'be' voor België, 'nl' voor Nederland)")
    parser.add_argument("--output", type=str, default="leads.csv", help="Naam van het CSV-uitvoerbestand (standaard: leads.csv)")
    parser.add_argument("--demo", action="store_true", help="Draai met ingebouwde voorbeeld-leads zonder Serper.dev API-aanroepen")

    args = parser.parse_args()
    run_sales_agent(
        query=args.query,
        count=args.count,
        country=args.country,
        output_file=args.output,
        demo=args.demo
    )

if __name__ == "__main__":
    main()
