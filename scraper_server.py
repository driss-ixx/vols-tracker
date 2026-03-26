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
CORS(app)

_cache = {}

def cache_key(dep, arr, date_out, date_in, adults):
    return f"{dep}_{arr}_{date_out}_{date_in}_{adults}"

def is_cached(key):
    if key not in _cache: return False
    return (time.time() - _cache[key]["ts"]) < 3600

def scrape_google_flights(dep, arr, date_out, date_in, adults="1"):
    """Scrape Google Flights avec patchright (Chrome visible, furtif)."""
    from patchright.sync_api import sync_playwright

    url = (
        f"https://www.google.com/travel/flights?"
        f"hl=fr#flt={dep}.{arr}.{date_out}*{arr}.{dep}.{date_in}"
        f";c:EUR;e:1;sd:1;t:f;tt:o"
    )
    print(f"[{datetime.now():%H:%M:%S}] Scraping {dep}→{arr} {date_out}/{date_in}...")
    flights = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        time.sleep(4)

        # Cookies
        for txt in ["Tout accepter", "Accept all", "Accepter"]:
            try:
                page.click(f"button:has-text('{txt}')", timeout=2500)
                time.sleep(2)
                break
            except Exception:
                pass

        # Attendre résultats
        for sel in ["li.pIav2d", "[jsname='IWWDBc'] li", "div[jsname='t2M3Fb']"]:
            try:
                page.wait_for_selector(sel, timeout=15000)
                print(f"  Sélecteur trouvé: {sel}")
                break
            except Exception:
                pass
        time.sleep(3)

        try:
            content = page.inner_text("body")
        except Exception:
            content = ""

        cards = page.query_selector_all("li.pIav2d, [jsname='IWWDBc'] li")
        print(f"  {len(cards)} cartes DOM, {len(content)} chars")

        airlines_kw = ["TAP", "Royal Air Maroc", "Air France", "Transavia",
                       "Air Sénégal", "Air Senegal", "Cabo Verde", "Iberia",
                       "Ryanair", "easyJet", "Vueling", "Lufthansa", "KLM",
                       "British Airways", "Turkish Airlines", "Emirates", "TAAG"]

        for i, card in enumerate(cards[:10]):
            try:
                txt = card.inner_text()
                if not txt.strip(): continue
                pm = re.search(r"(\d{2,5})\s*€", txt) or re.search(r"€\s*(\d{2,5})", txt)
                price = int(pm.group(1)) if pm else None
                if not price: continue
                times = re.findall(r"\b(\d{1,2}:\d{2})\b", txt)
                if len(times) < 2: continue
                dm = re.search(r"(\d+)\s*h\s*(\d+)?\s*min", txt)
                dur_h = int(dm.group(1)) if dm else 0
                dur_m = int(dm.group(2) or 0) if dm else 0
                airline = next((k for k in airlines_kw if k.lower() in txt.lower()), "Google Flights")
                if any(x in txt for x in ["Sans escale", "Nonstop", "Direct"]):
                    stops, stop_txt = 0, "Direct"
                elif "1 escale" in txt:
                    stops, stop_txt = 1, "1 escale"
                elif "2 escales" in txt:
                    stops, stop_txt = 2, "2 escales"
                else:
                    stops, stop_txt = 1, "1 escale"
                flights.append({
                    "rank": i+1, "airline": airline, "code": airline[:2].upper(),
                    "dep": times[0], "arr": times[1], "depA": dep, "arrA": arr,
                    "dur": f"{dur_h}h{dur_m:02d}", "dur_min": dur_h*60+dur_m,
                    "stops": stops, "stop_txt": stop_txt, "price": price,
                    "ret": "Aller-retour",
                    "source": f"Google Flights · {datetime.now():%d/%m}",
                    "url": url, "best": False,
                    "offer_id": f"live_{datetime.now():%Y%m%d}_{i}",
                    "updated_at": datetime.utcnow().isoformat()+"Z",
                })
            except Exception as e:
                print(f"  carte {i}: {e}")

        # Fallback regex sur texte complet
        if not flights and content:
            print("  fallback regex...")
            blocks = re.findall(
                r"(\d{1,2}:\d{2})[^\d]{1,50}(\d{1,2}:\d{2})[^€]{5,300}?(\d+)\s*h\s*(\d+)?\s*min[^€]{0,150}?(\d{3,5})\s*€",
                content
            )
            seen = set()
            for i, (dt, at, h, m, price) in enumerate(blocks[:10]):
                key = f"{dt}{at}{price}"
                if key in seen: continue
                seen.add(key)
                flights.append({
                    "rank": i+1, "airline": "Google Flights", "code": "GF",
                    "dep": dt, "arr": at, "depA": dep, "arrA": arr,
                    "dur": f"{h}h{m or '00'}", "dur_min": int(h)*60+int(m or 0),
                    "stops": 1, "stop_txt": "1 escale", "price": int(price),
                    "ret": "Aller-retour",
                    "source": f"Google Flights · {datetime.now():%d/%m}",
                    "url": url, "best": False,
                    "offer_id": f"rx_{datetime.now():%Y%m%d}_{i}",
                    "updated_at": datetime.utcnow().isoformat()+"Z",
                })

        browser.close()

    flights.sort(key=lambda x: x["price"])
    for i, f in enumerate(flights):
        f["rank"] = i + 1
        f["best"] = i == 0
    print(f"  → {len(flights)} vols extraits")
    return flights[:10]


@app.route("/search")
def search():
    dep      = request.args.get("dep", "PAR").upper()
    arr      = request.args.get("arr", "RAI").upper()
    date_out = request.args.get("out", "")
    date_in  = request.args.get("in", "")
    adults   = request.args.get("adults", "1")

    if not date_out or not date_in:
        return jsonify({"error": "Paramètres out et in requis"}), 400

    key = cache_key(dep, arr, date_out, date_in, adults)
    if is_cached(key):
        print(f"Cache hit: {key}")
        return jsonify({"flights": _cache[key]["data"], "source": "cache"})

    try:
        flights = scrape_google_flights(dep, arr, date_out, date_in, adults)
        if flights:
            _cache[key] = {"data": flights, "ts": time.time()}
        return jsonify({
            "flights": flights,
            "source": "live",
            "scraped_at": datetime.utcnow().isoformat()+"Z",
            "count": len(flights)
        })
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({"error": str(e), "flights": []}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


if __name__ == "__main__":
    print("="*50)
    print("🛫  Serveur vols-tracker")
    print("    http://localhost:8888")
    print("="*50)
    app.run(host="127.0.0.1", port=8888, debug=False)
