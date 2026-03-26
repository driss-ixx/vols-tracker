#!/usr/bin/env python3
"""
fetch_vols.py — Récupère les prix Paris→Praia via SerpAPI
Stocke dans Supabase. Lancé chaque matin à 5h par launchd.

Usage : python3 fetch_vols.py
"""

import os, sys, json, urllib.request, urllib.parse
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────
SERPAPI_KEY   = os.environ.get("SERPAPI_KEY", "")
SUPABASE_URL  = "https://iagsrbmeviwmozauhenk.supabase.co"
SUPABASE_KEY  = os.environ.get("SUPABASE_SERVICE_KEY", "")

PARAMS = {
    "engine": "google_flights",
    "departure_id": "PAR",
    "arrival_id": "RAI",
    "outbound_date": "2026-05-06",
    "return_date": "2026-05-13",
    "currency": "EUR",
    "hl": "fr",
    "type": "1",
    "adults": "1",
    "sort_by": "1",
    "api_key": SERPAPI_KEY,
}

# ── Helpers ─────────────────────────────────────────────────────────────────
def fetch(url, method="GET", data=None, headers=None):
    req = urllib.request.Request(url, method=method,
          data=json.dumps(data).encode() if data else None,
          headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def serpapi_search():
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(PARAMS)
    print(f"[{datetime.now():%H:%M:%S}] → SerpAPI GET {url[:80]}...")
    req = urllib.request.Request(url, headers={"User-Agent": "vols-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def parse(data):
    results = []
    all_offers = list(data.get("best_flights", [])) + list(data.get("other_flights", []))
    for i, offer in enumerate(all_offers):
        flights = offer.get("flights", [])
        if not flights:
            continue
        first, last = flights[0], flights[-1]
        stops = len(flights) - 1
        stop_airports = " + ".join(f["arrival_airport"]["id"] for f in flights[:-1] if f.get("arrival_airport"))
        stop_txt = "Direct" if stops == 0 else f"{stops} escale(s) · {stop_airports}"

        dur = offer.get("total_duration", 0)
        dur_txt = f"{dur // 60}h{str(dur % 60).zfill(2)}"
        airlines = "+".join(dict.fromkeys(f.get("airline", "?") for f in flights))

        dep_time = (first.get("departure_airport") or {}).get("time", "")[:5]
        arr_time = (last.get("arrival_airport") or {}).get("time", "")[:5]
        dep_a = (first.get("departure_airport") or {}).get("id", "PAR")
        arr_a = (last.get("arrival_airport") or {}).get("id", "RAI")

        results.append({
            "rank": i + 1,
            "airline": airlines,
            "code": airlines[:2].upper(),
            "dep": dep_time,
            "arr": arr_time,
            "depA": dep_a,
            "arrA": arr_a,
            "dur": dur_txt,
            "dur_min": dur,
            "stops": stops,
            "stop_txt": stop_txt,
            "price": offer.get("price"),
            "ret": "Voir Google Flights",
            "source": f"Google Flights · {datetime.now():%d/%m}",
            "url": "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI2LTA1LTA2agcIARIDUEFScgcIARIDUkFJGh4SCjIwMjYtMDUtMTNqBwgBEgNSQUlyBwgBEgNQQVIiASoqAggBQgIIAUgB&hl=fr&curr=EUR",
            "best": i == 0,
            "offer_id": f"py_{datetime.now():%Y%m%d}_{i}",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        })
    return sorted(results, key=lambda x: x["price"] or 9999)[:10]

def supabase(path, method="GET", body=None):
    url = SUPABASE_URL + "/rest/v1/" + path
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else {}

def main():
    if not SERPAPI_KEY:
        print("ERREUR : SERPAPI_KEY manquante. Exporter : export SERPAPI_KEY=ta_cle")
        sys.exit(1)
    if not SUPABASE_KEY:
        print("ERREUR : SUPABASE_SERVICE_KEY manquante.")
        sys.exit(1)

    # 1. Fetch SerpAPI
    raw = serpapi_search()
    flights = parse(raw)
    if not flights:
        print("ERREUR : aucun vol parsé. Réponse SerpAPI :", json.dumps(raw)[:500])
        sys.exit(1)
    print(f"✓ {len(flights)} vols trouvés. Moins cher : {flights[0]['price']} EUR ({flights[0]['airline']})")

    # 2. Vider vols_praia
    supabase("vols_praia?id=gte.0", method="DELETE")

    # 3. Insérer les nouveaux
    supabase("vols_praia", method="POST", body=flights)
    print("✓ Supabase mis à jour")

    # 4. Log
    supabase("vols_praia_log", method="POST", body={
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "nb_results": len(flights),
        "min_price": flights[0]["price"],
    })
    print(f"✓ Log enregistré. Terminé à {datetime.now():%H:%M:%S}")

if __name__ == "__main__":
    main()
