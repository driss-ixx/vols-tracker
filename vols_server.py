#!/usr/bin/env python3
"""
vols_server.py — Serveur local de recherche de vols
Utilise fast-flights avec playwright (mode local) — fonctionne pour TOUTE route.
Lance sur http://localhost:8888

Usage : python3 vols_server.py
"""

import json, re, time, os, sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

VENV_PYTHON = "/Users/drissixx/Claude/Antigravity/.venv/bin/python3.14"

_cache = {}

def cache_key(dep, arr, date_out, date_in, adults):
    return f"{dep}_{arr}_{date_out}_{date_in}_{adults}"

def is_cached(key):
    if key not in _cache: return False
    return (time.time() - _cache[key]["ts"]) < 3600

def parse_price(p):
    if p is None: return None
    s = str(p).replace("€","").replace("$","").replace(",","").strip()
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None

def parse_duration(d):
    if not d: return 0
    m = re.search(r"(\d+)\s*hr?\s*(\d+)?\s*min?", str(d))
    if m: return int(m.group(1)) * 60 + int(m.group(2) or 0)
    m2 = re.search(r"(\d+)\s*hr?", str(d))
    return int(m2.group(1)) * 60 if m2 else 0

def search_flights(dep, arr, date_out, date_in, adults=1):
    from fast_flights import Passengers, get_flights, FlightData

    print(f"[{datetime.now():%H:%M:%S}] Recherche {dep}→{arr} {date_out}/{date_in}...")
    result = get_flights(
        flight_data=[
            FlightData(date=date_out, from_airport=dep, to_airport=arr),
            FlightData(date=date_in, from_airport=arr, to_airport=dep),
        ],
        trip="round-trip",
        passengers=Passengers(adults=int(adults)),
        seat="economy",
        fetch_mode="local",
    )
    print(f"  → {len(result.flights)} vols bruts")

    url = (
        f"https://www.google.com/travel/flights?"
        f"hl=fr#flt={dep}.{arr}.{date_out}*{arr}.{dep}.{date_in}"
        f";c:EUR;e:1;sd:1;t:f;tt:o"
    )
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now().strftime("%d/%m")

    flights = []
    seen = set()
    rank = 0

    for f in result.flights:
        price = parse_price(f.price)
        if not price or price > 9999: continue
        key = f"{f.departure}|{f.arrival}|{price}"
        if key in seen: continue
        seen.add(key)
        rank += 1

        dur_min = parse_duration(f.duration)
        dur_h, dur_m = divmod(dur_min, 60)
        dur_txt = f"{dur_h}h{dur_m:02d}" if dur_min else str(f.duration or "?")
        stops = f.stops if f.stops is not None else 0
        stop_txt = "Direct" if stops == 0 else f"{stops} escale{'s' if stops > 1 else ''}"

        flights.append({
            "rank": rank,
            "airline": str(f.name or ""),
            "code": str(f.name or "")[:2].upper(),
            "dep": str(f.departure or ""),
            "arr": str(f.arrival or ""),
            "depA": dep, "arrA": arr,
            "dur": dur_txt, "dur_min": dur_min,
            "stops": stops, "stop_txt": stop_txt,
            "price": price,
            "ret": "Aller-retour",
            "source": f"Google Flights · {today}",
            "url": url,
            "best": rank == 1,
            "updated_at": now,
        })
        if rank >= 15: break

    return flights


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._json(200, {"status": "ok"})
            return

        if parsed.path == "/search":
            params = parse_qs(parsed.query)
            dep = params.get("dep", ["ORY"])[0].upper()
            arr = params.get("arr", ["RAI"])[0].upper()
            date_out = params.get("out", [""])[0]
            date_in = params.get("in", [""])[0]
            adults = params.get("adults", ["1"])[0]

            if not date_out or not date_in:
                self._json(400, {"error": "Paramètres out et in requis"})
                return

            key = cache_key(dep, arr, date_out, date_in, adults)
            if is_cached(key):
                print(f"Cache hit: {key}")
                self._json(200, {"flights": _cache[key]["data"], "source": "cache"})
                return

            try:
                flights = search_flights(dep, arr, date_out, date_in, adults)
                if flights:
                    _cache[key] = {"data": flights, "ts": time.time()}
                self._json(200, {
                    "flights": flights,
                    "source": "live",
                    "count": len(flights),
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                print(f"Erreur: {e}")
                self._json(500, {"error": str(e), "flights": []})
            return

        self._json(404, {"error": "Not found"})

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"  {args[0]} {args[1]}")


if __name__ == "__main__":
    print("=" * 50)
    print("  Vols Tracker — Serveur local")
    print("  http://localhost:8888")
    print("  Utilise playwright (fast-flights local)")
    print("=" * 50)
    server = HTTPServer(("127.0.0.1", 8888), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServeur arrêté.")
