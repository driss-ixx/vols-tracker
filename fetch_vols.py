#!/usr/bin/env python3
"""
fetch_vols.py — Scrape Google Flights avec Playwright (headless Chrome)
Zéro API key, zéro compte, 100% gratuit.
Lance à 5h par launchd → stocke dans Supabase.

Usage : python3 fetch_vols.py
"""

import json, re, sys, os, time, urllib.request
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────
SUPABASE_URL = "https://iagsrbmeviwmozauhenk.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

GOOGLE_FLIGHTS_URL = (
    "https://www.google.com/travel/flights/search"
    "?tfs=CBwQAhoeEgoyMDI2LTA1LTA2agcIARIDUEFScgcIARIDUkFJGh4S"
    "CjIwMjYtMDUtMTNqBwgBEgNSQUlyBwgBEgNQQVIiASoqAggBQgIIAUgB"
    "&hl=fr&curr=EUR"
)

# ── Supabase helpers ────────────────────────────────────────────────────────
def sb_request(path, method="GET", body=None):
    url = SUPABASE_URL + "/rest/v1/" + path
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": "Bearer " + SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt.strip() else {}

# ── Playwright scraper ──────────────────────────────────────────────────────
def scrape_flights():
    from playwright.sync_api import sync_playwright

    flights = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ])
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
        )
        page = ctx.new_page()

        print(f"[{datetime.now():%H:%M:%S}] → Navigation Google Flights...")
        page.goto(GOOGLE_FLIGHTS_URL, wait_until="networkidle", timeout=40000)
        time.sleep(3)

        # Accepter cookies si présents
        try:
            page.click("button:has-text('Tout accepter')", timeout=3000)
            time.sleep(1)
        except Exception:
            pass
        try:
            page.click("button:has-text('Accept all')", timeout=2000)
            time.sleep(1)
        except Exception:
            pass

        # Attendre les résultats
        try:
            page.wait_for_selector("[data-ved] .YMlIz", timeout=15000)
        except Exception:
            try:
                page.wait_for_selector("li.pIav2d", timeout=10000)
            except Exception:
                pass
        time.sleep(2)

        # Extraire le texte brut pour chercher les prix
        content = page.inner_text("body")

        # Extraire les cartes de vols via sélecteurs Google Flights
        cards = page.query_selector_all("li.pIav2d, [jsname='IWWDBc'] li")
        print(f"[{datetime.now():%H:%M:%S}] → {len(cards)} cartes trouvées")

        for i, card in enumerate(cards[:8]):
            try:
                txt = card.inner_text()
                lines = [l.strip() for l in txt.split("\n") if l.strip()]

                # Chercher prix (nombre suivi de €)
                price_match = re.search(r"(\d{2,4})\s*€", txt)
                if not price_match:
                    price_match = re.search(r"€\s*(\d{2,4})", txt)
                price = int(price_match.group(1)) if price_match else None

                # Chercher horaires (HH:MM)
                times = re.findall(r"\b(\d{1,2}:\d{2})\b", txt)

                # Chercher durée
                dur_match = re.search(r"(\d+)\s*h\s*(\d+)\s*min", txt)
                dur_txt = f"{dur_match.group(1)}h{dur_match.group(2)}" if dur_match else "?"
                dur_min = (int(dur_match.group(1)) * 60 + int(dur_match.group(2))) if dur_match else 0

                # Chercher compagnie
                airlines_kw = ["TAP", "Royal Air Maroc", "Air France", "Transavia",
                                "Air Sénégal", "Air Senegal", "Cabo Verde", "Iberia", "Ryanair"]
                airline = "Inconnu"
                for kw in airlines_kw:
                    if kw.lower() in txt.lower():
                        airline = kw
                        break

                # Escales
                if "Sans escale" in txt or "Nonstop" in txt or "Direct" in txt:
                    stops, stop_txt = 0, "Direct"
                elif "1 escale" in txt or "1 stop" in txt:
                    stops = 1
                    esc_match = re.search(r"1 escale[^\n]*\n([A-Z]{3})", txt)
                    stop_txt = "1 escale · " + (esc_match.group(1) if esc_match else "?")
                elif "2 escales" in txt:
                    stops, stop_txt = 2, "2 escales"
                else:
                    stops, stop_txt = 1, "1 escale"

                if price and len(times) >= 2:
                    flights.append({
                        "rank": i + 1,
                        "airline": airline,
                        "code": airline[:2].upper(),
                        "dep": times[0],
                        "arr": times[1],
                        "depA": "ORY" if i % 2 == 0 else "CDG",
                        "arrA": "RAI",
                        "dur": dur_txt,
                        "dur_min": dur_min,
                        "stops": stops,
                        "stop_txt": stop_txt,
                        "price": price,
                        "ret": "Voir Google Flights",
                        "source": f"Google Flights · {datetime.now():%d/%m}",
                        "url": GOOGLE_FLIGHTS_URL,
                        "best": False,
                        "offer_id": f"pw_{datetime.now():%Y%m%d}_{i}",
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                    })
            except Exception as e:
                print(f"  ⚠ carte {i} ignorée : {e}")
                continue

        # Fallback : extraction par regex sur tout le texte
        if not flights:
            print("→ Fallback extraction regex...")
            price_blocks = re.findall(
                r"(\d{1,2}:\d{2})[^\d]*(\d{1,2}:\d{2})[^€]*(\d+)\s*h\s*(\d+)\s*min[^€]*?(\d{3,4})\s*€",
                content
            )
            for i, (dep, arr, h, m, price) in enumerate(price_blocks[:8]):
                flights.append({
                    "rank": i + 1,
                    "airline": "Voir Google Flights",
                    "code": "?",
                    "dep": dep, "arr": arr,
                    "depA": "PAR", "arrA": "RAI",
                    "dur": f"{h}h{m}", "dur_min": int(h)*60+int(m),
                    "stops": 1, "stop_txt": "1 escale",
                    "price": int(price),
                    "ret": "Voir Google Flights",
                    "source": f"Google Flights · {datetime.now():%d/%m}",
                    "url": GOOGLE_FLIGHTS_URL,
                    "best": i == 0,
                    "offer_id": f"pw_rx_{datetime.now():%Y%m%d}_{i}",
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                })

        browser.close()

    # Trier par prix, marquer le moins cher
    flights.sort(key=lambda x: x["price"] or 9999)
    if flights:
        flights[0]["best"] = True
        for i, f in enumerate(flights):
            f["rank"] = i + 1

    return flights[:10]

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    if not SUPABASE_KEY:
        print("ERREUR : SUPABASE_SERVICE_KEY manquante.")
        print("Exporter : export SUPABASE_SERVICE_KEY=ta_cle_service_role")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"Vols tracker — {datetime.now():%d/%m/%Y %H:%M:%S}")
    print(f"{'='*50}")

    flights = scrape_flights()

    if not flights:
        print("ERREUR : aucun vol extrait. La page a peut-être changé.")
        sys.exit(1)

    print(f"\n✓ {len(flights)} vols extraits :")
    for f in flights:
        print(f"  {f['rank']}. {f['airline']:20} {f['dep']}→{f['arr']}  {f['dur']:6}  {f['price']} EUR")

    # Vider + réinsérer dans Supabase
    sb_request("vols_praia?id=gte.0", method="DELETE")
    sb_request("vols_praia", method="POST", body=flights)
    print("\n✓ Supabase mis à jour")

    sb_request("vols_praia_log", method="POST", body={
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "nb_results": len(flights),
        "min_price": flights[0]["price"],
    })
    print(f"✓ Log enregistré. Prix min : {flights[0]['price']} EUR ({flights[0]['airline']})")
    print(f"✓ Terminé à {datetime.now():%H:%M:%S}\n")

if __name__ == "__main__":
    main()
