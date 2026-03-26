#!/usr/bin/env python3
"""
scraper_server.py — Serveur local de recherche de vols
Lance sur http://localhost:8888
La page vols-praia.html l'appelle pour obtenir des vrais prix.

Usage : python3 scraper_server.py
"""

import json, re, time, os
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Autorise les appels depuis le fichier HTML local

SUPABASE_URL = "https://iagsrbmeviwmozauhenk.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# Cache en mémoire : évite de rescraper la même route dans la même heure
_cache = {}

def cache_key(dep, arr, date_out, date_in, adults):
    return f"{dep}_{arr}_{date_out}_{date_in}_{adults}"

def is_cached(key):
    if key not in _cache: return False
    age = time.time() - _cache[key]["ts"]
    return age < 3600  # 1h de cache

def scrape_google_flights(dep, arr, date_out, date_in, adults="1"):
    """Scrape Google Flights avec camoufox (anti-bot)."""
    from camoufox.sync_api import Camoufox

    # URL Google Flights format générique
    url = (
        f"https://www.google.com/travel/flights/search"
        f"?tfs=CBwQAho"
        f"&hl=fr&curr=EUR"
    )
    # URL plus directe avec paramètres
    url2 = (
        f"https://www.google.com/travel/flights?"
        f"hl=fr#flt={dep}.{arr}.{date_out}*{arr}.{dep}.{date_in}"
        f";c:EUR;e:1;sd:1;t:f;tt:o"
    )

    flights = []
    print(f"[{datetime.now():%H:%M:%S}] Scraping {dep}→{arr} {date_out}/{date_in}...")

    with Camoufox(headless=True, geoip=True) as browser:
        page = browser.new_page()
        page.goto(url2, timeout=45000, wait_until="networkidle")
        time.sleep(3)

        # Accepter cookies
        for txt in ["Tout accepter", "Accept all", "Accepter tout"]:
            try:
                page.click(f"button:has-text('{txt}')", timeout=2000)
                time.sleep(1)
                break
            except Exception:
                pass

        # Attendre les résultats
        for sel in ["li.pIav2d", "[jsname='IWWDBc'] li", ".YMlIz"]:
            try:
                page.wait_for_selector(sel, timeout=12000)
                break
            except Exception:
                pass
        time.sleep(2)

        content = page.inner_text("body")
        cards = page.query_selector_all("li.pIav2d, [jsname='IWWDBc'] li")
        print(f"  {len(cards)} cartes trouvées")

        for i, card in enumerate(cards[:10]):
            try:
                txt = card.inner_text()
                if not txt.strip(): continue

                # Prix
                pm = re.search(r"(\d{2,5})\s*€", txt) or re.search(r"€\s*(\d{2,5})", txt)
                price = int(pm.group(1)) if pm else None
                if not price: continue

                # Horaires
                times = re.findall(r"\b(\d{1,2}:\d{2})\b", txt)
                if len(times) < 2: continue

                # Durée
                dm = re.search(r"(\d+)\s*h\s*(\d+)?\s*min", txt)
                if dm:
                    dur_h, dur_m = int(dm.group(1)), int(dm.group(2) or 0)
                    dur_txt = f"{dur_h}h{dur_m:02d}"
                    dur_min = dur_h * 60 + dur_m
                else:
                    dm2 = re.search(r"(\d+)\s*h(?:\s|$)", txt)
                    if dm2:
                        dur_h = int(dm2.group(1))
                        dur_txt = f"{dur_h}h00"
                        dur_min = dur_h * 60
                    else:
                        dur_txt, dur_min = "?", 0

                # Compagnie
                airlines_kw = ["TAP", "Royal Air Maroc", "Air France", "Transavia",
                               "Air Sénégal", "Air Senegal", "Cabo Verde Airlines",
                               "Iberia", "Ryanair", "easyJet", "Vueling", "Lufthansa",
                               "British Airways", "KLM", "Turkish Airlines", "Emirates",
                               "Air Portugal", "TAAG", "TACV"]
                airline = "Voir comparateur"
                for kw in airlines_kw:
                    if kw.lower() in txt.lower():
                        airline = kw
                        break

                # Escales
                if any(x in txt for x in ["Sans escale", "Nonstop", "Direct"]):
                    stops, stop_txt = 0, "Direct"
                elif "1 escale" in txt or "1 stop" in txt:
                    em = re.search(r"1 escale[^\n]*\n([A-Z]{3})", txt)
                    stops, stop_txt = 1, "1 escale · " + (em.group(1) if em else "?")
                elif "2 escales" in txt:
                    stops, stop_txt = 2, "2 escales"
                else:
                    stops, stop_txt = 1, "1 escale"

                flights.append({
                    "rank": i + 1,
                    "airline": airline,
                    "code": airline[:2].upper(),
                    "dep": times[0],
                    "arr": times[1],
                    "depA": dep,
                    "arrA": arr,
                    "dur": dur_txt,
                    "dur_min": dur_min,
                    "stops": stops,
                    "stop_txt": stop_txt,
                    "price": price,
                    "ret": "Aller-retour",
                    "source": f"Google Flights · {datetime.now():%d/%m}",
                    "url": url2,
                    "best": False,
                    "offer_id": f"live_{datetime.now():%Y%m%d}_{i}",
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                })
            except Exception as e:
                print(f"  carte {i} ignorée: {e}")

        # Fallback regex
        if not flights:
            print("  fallback regex...")
            blocks = re.findall(
                r"(\d{1,2}:\d{2})[^\d]*(\d{1,2}:\d{2})[^€]*(\d+)\s*h\s*(\d+)?\s*min[^€]*?(\d{3,5})\s*€",
                content
            )
            for i, groups in enumerate(blocks[:8]):
                dep_t, arr_t, h, m, price = groups
                flights.append({
                    "rank": i + 1,
                    "airline": "Voir Google Flights",
                    "code": "??",
                    "dep": dep_t, "arr": arr_t,
                    "depA": dep, "arrA": arr,
                    "dur": f"{h}h{m or '00'}", "dur_min": int(h)*60+int(m or 0),
                    "stops": 1, "stop_txt": "1 escale",
                    "price": int(price),
                    "ret": "Aller-retour",
                    "source": f"Google Flights · {datetime.now():%d/%m}",
                    "url": url2,
                    "best": i == 0,
                    "offer_id": f"rx_{datetime.now():%Y%m%d}_{i}",
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                })

    # Trier, marquer le meilleur
    flights.sort(key=lambda x: x["price"])
    for i, f in enumerate(flights):
        f["rank"] = i + 1
        f["best"] = i == 0

    return flights[:10]


@app.route("/search")
def search():
    dep    = request.args.get("dep", "PAR").upper()
    arr    = request.args.get("arr", "RAI").upper()
    date_out = request.args.get("out", "")
    date_in  = request.args.get("in", "")
    adults   = request.args.get("adults", "1")

    if not date_out or not date_in:
        return jsonify({"error": "Paramètres out et in requis"}), 400

    key = cache_key(dep, arr, date_out, date_in, adults)
    if is_cached(key):
        print(f"Cache hit: {key}")
        return jsonify({"flights": _cache[key]["data"], "source": "cache", "cached_at": _cache[key]["ts"]})

    try:
        flights = scrape_google_flights(dep, arr, date_out, date_in, adults)
        if flights:
            _cache[key] = {"data": flights, "ts": time.time()}
        return jsonify({
            "flights": flights,
            "source": "live",
            "scraped_at": datetime.utcnow().isoformat() + "Z",
            "count": len(flights)
        })
    except Exception as e:
        print(f"Erreur scraping: {e}")
        return jsonify({"error": str(e), "flights": []}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


if __name__ == "__main__":
    print("=" * 50)
    print("🛫  Serveur vols-tracker démarré")
    print("    http://localhost:8888")
    print("    /search?dep=PAR&arr=RAI&out=2026-05-06&in=2026-05-13")
    print("=" * 50)
    app.run(host="127.0.0.1", port=8888, debug=False)
