"""
api/search.py — Vercel Python serverless function
Recherche de vols via fast-flights (mode common + cookie SOCS)
GET /api/search?dep=ORY&arr=RAI&out=2026-05-06&in=2026-05-13&adults=1
"""

import json
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone

# Cookie SOCS Google = bypass GDPR consent wall
SOCS_COOKIE = "CAESEwgDEgk2MDYyMDcxOTIaAmZyIAEaBgiAnPq2BjIDeW91"


def patch_fast_flights():
    """Monkey-patch fast_flights.core.fetch pour injecter le cookie SOCS."""
    import fast_flights.core as ff_core
    from fast_flights.primp import Client

    def fetch_with_socs(params: dict):
        client = Client(impersonate="chrome_126", verify=False)
        res = client.get(
            "https://www.google.com/travel/flights",
            params=params,
            cookies={"SOCS": SOCS_COOKIE},
        )
        assert res.status_code == 200, f"{res.status_code} {res.text[:200]}"
        return res

    ff_core.fetch = fetch_with_socs


def parse_price(p):
    if p is None:
        return None
    s = str(p).replace("€", "").replace("$", "").replace(",", "").strip()
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def parse_duration(d):
    if not d:
        return 0
    m = re.search(r"(\d+)\s*hr?\s*(\d+)?\s*min?", str(d))
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    m2 = re.search(r"(\d+)\s*hr?", str(d))
    return int(m2.group(1)) * 60 if m2 else 0


def search_flights(dep, arr, date_out, date_in, adults=1):
    patch_fast_flights()
    from fast_flights import Passengers, get_flights, FlightData

    result = get_flights(
        flight_data=[
            FlightData(date=date_out, from_airport=dep, to_airport=arr),
            FlightData(date=date_in, from_airport=arr, to_airport=dep),
        ],
        trip="round-trip",
        passengers=Passengers(adults=int(adults)),
        seat="economy",
        fetch_mode="common",
    )

    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now().strftime("%d/%m")
    url = (
        f"https://www.google.com/travel/flights?"
        f"hl=fr#flt={dep}.{arr}.{date_out}*{arr}.{dep}.{date_in}"
        f";c:EUR;e:1;sd:1;t:f;tt:o"
    )

    flights = []
    seen = set()
    rank = 0

    for f in result.flights:
        price = parse_price(f.price)
        if not price or price > 9999:
            continue
        key = f"{f.departure}|{f.arrival}|{price}"
        if key in seen:
            continue
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
            "depA": dep,
            "arrA": arr,
            "dur": dur_txt,
            "dur_min": dur_min,
            "stops": stops,
            "stop_txt": stop_txt,
            "price": price,
            "ret": "Aller-retour",
            "source": f"Google Flights · {today}",
            "url": url,
            "best": rank == 1,
            "updated_at": now,
        })

        if rank >= 15:
            break

    return flights


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        dep = params.get("dep", ["ORY"])[0].upper()
        arr = params.get("arr", ["RAI"])[0].upper()
        date_out = params.get("out", [""])[0]
        date_in = params.get("in", [""])[0]
        adults = params.get("adults", ["1"])[0]

        if not date_out or not date_in:
            self._json(400, {"error": "Paramètres out et in requis"})
            return

        try:
            flights = search_flights(dep, arr, date_out, date_in, adults)
            self._json(200, {
                "flights": flights,
                "count": len(flights),
                "source": "live",
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            self._json(500, {"error": str(e), "flights": []})

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
