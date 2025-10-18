import re
import time
import csv
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
import pandas as pd

BASE = "https://medicoshospitales.sanitas.es"
START_URL = f"{BASE}/listado-medicos.php"

# Be polite & identifiable. Include a contact email/domain you control.
HEADERS = {
    "User-Agent": "SanitasDirectoryResearchBot/1.0 (+contact: you@example.com)"
}

# ---- Helpers ---------------------------------------------------------------

def get_soup(url, *, params=None, sleep=1.5):
    """GET a URL, return BeautifulSoup. Simple backoff on 429/503."""
    for attempt in range(5):
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        if r.status_code in (429, 503):
            wait = min(10, 2 * (attempt + 1))
            time.sleep(wait)
            continue
        r.raise_for_status()
        time.sleep(sleep)
        # Some Spanish sites send latin-1; let requests guess, fallback to utf-8
        r.encoding = r.encoding or "utf-8"
        return BeautifulSoup(r.text, "lxml")
    raise RuntimeError(f"Could not fetch {url} after retries")

PROFILE_PATH_RE = re.compile(r"^/[\w\-]+(?:-[\w\-]+)*$")  # e.g. /dr-juan-perez
ABS_PROFILE_RE   = re.compile(r"^https?://medicoshospitales\.sanitas\.es/[^/?#]+$")

def is_profile_url(href: str) -> bool:
    if not href:
        return False
    # Accept absolute or relative clean slugs without query
    return bool(ABS_PROFILE_RE.match(href) or PROFILE_PATH_RE.match(href))

def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()

PHONE_RE = re.compile(r"(?:\+34\s*)?(?:\(?\d{2,3}\)?[\s\-\.]?\d{2,3}[\s\-\.]?\d{2,3}[\s\-\.]?\d{2,3})")

# ---- Stage 1: crawl listing pages & collect profile links ------------------

def collect_profile_urls(start_url=START_URL, max_pages=999):
    seen = set()
    to_visit = [start_url]
    profile_urls = []

    pages_crawled = 0
    while to_visit and pages_crawled < max_pages:
        url = to_visit.pop(0)
        soup = get_soup(url)

        # 1) Find links that look like profile pages
        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            abs_url = urljoin(BASE, href)
            # Stay on same host
            if urlparse(abs_url).netloc != urlparse(BASE).netloc:
                continue
            if is_profile_url(abs_url):
                if abs_url not in seen:
                    seen.add(abs_url)
                    profile_urls.append(abs_url)

        # 2) Find a pagination "next" link (common patterns)
        next_candidates = []
        next_candidates += soup.select("a[rel='next']")
        next_candidates += [a for a in soup.select("a[href]") if "siguiente" in a.get_text(strip=True).lower()]
        next_candidates += soup.select(".pagination a, nav[aria-label*='pagination'] a")

        next_url = None
        for a in next_candidates:
            txt = (a.get_text() or "").strip().lower()
            if "sig" in txt or "siguiente" in txt or (a.get("rel") and "next" in a.get("rel")):
                href = a.get("href")
                if href:
                    candidate = urljoin(BASE, href)
                    if candidate not in seen and "listado-medicos" in candidate:
                        next_url = candidate
                        break

        pages_crawled += 1
        if next_url and next_url not in to_visit:
            to_visit.append(next_url)

    return sorted(set(profile_urls))

# ---- Stage 2: visit profiles & parse fields --------------------------------

def parse_profile(url):
    soup = get_soup(url, sleep=1.2)

    # Name (try multiple selectors)
    name = None
    for sel in [
        "h1", 
        ".doctor-name", 
        ".professional-name", 
        "[itemprop='name']",
        "header h1",
        ".perfil h1"
    ]:
        el = soup.select_one(sel)
        if el and clean_text(el.text):
            name = clean_text(el.text)
            break

    # Specialties (common labels in ES: Especialidad / Especialidades)
    specialties = []
    for sel in [
        ".specialty, .specialties li, .especialidad, .especialidades li",
        "[data-field='specialty']",
        "section:has(h2:contains('Especial')) li",
        "section:has(h3:contains('Especial')) li"
    ]:
        for el in soup.select(sel):
            t = clean_text(el.text)
            if t and t.lower() not in ("-", "ver más"):
                specialties.append(t)
        if specialties:
            break
    specialties = sorted(set(specialties))

    # Centers / Hospitals (look for common labels)
    centers = []
    for sel in [
        ".centro, .centros li, .hospital, .hospitales li",
        "section:has(h2:contains('Centro')) li",
        "section:has(h2:contains('Hospital')) li",
        "section:has(h3:contains('Centro')) li",
        "section:has(h3:contains('Hospital')) li"
    ]:
        for el in soup.select(sel):
            t = clean_text(el.text)
            if t:
                centers.append(t)
        if centers:
            break
    centers = sorted(set(centers))

    # Bio / resumen
    bio = None
    for sel in [
        "section:has(h2:contains('Biografía')) p",
        "section:has(h2:contains('Resumen')) p",
        "section:has(h3:contains('Biografía')) p",
        "section:has(h3:contains('Resumen')) p",
        "article p"
    ]:
        ps = [clean_text(p.text) for p in soup.select(sel)]
        longish = " ".join([p for p in ps if len(p) > 60])
        if longish:
            bio = longish[:500]  # keep it short
            break

    # Any phone numbers on the page
    phones = sorted(set(PHONE_RE.findall(soup.get_text(separator=" "))))

    return {
        "profile_url": url,
        "name": name,
        "specialties": "; ".join(specialties) if specialties else None,
        "centers": "; ".join(centers) if centers else None,
        "phones": "; ".join(phones) if phones else None,
        "bio_excerpt": bio
    }

# ---- Run all ---------------------------------------------------------------

if __name__ == "__main__":
    print("Recolectando enlaces de perfiles...")
    profile_urls = collect_profile_urls(START_URL, max_pages=200)
    print(f"Perfiles detectados: {len(profile_urls)}")

    rows = []
    for i, url in enumerate(profile_urls, 1):
        try:
            row = parse_profile(url)
            rows.append(row)
        except Exception as e:
            print(f"[{i}/{len(profile_urls)}] Error en {url}: {e}")
        if i % 20 == 0:
            print(f"  Progreso: {i}/{len(profile_urls)}")

    df = pd.DataFrame(rows)
    df.to_csv("sanitas_doctores.csv", index=False)
    print(f"Guardado {len(df)} filas en sanitas_doctores.csv")
