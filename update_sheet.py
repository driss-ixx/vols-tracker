#!/usr/bin/env python3
"""
update_sheet.py — Récupère les vols Google Flights et met à jour le Google Sheet
Usage : python3 update_sheet.py [--dep ORY] [--arr RAI] [--out 2026-05-06] [--in 2026-05-13]
Lancé automatiquement à 5h par launchd.
"""

import json, urllib.request, sys, os, re, argparse
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────────────
TOKEN_FILE  = os.path.expanduser("~/.claude/google-tokens/didigum@gmail.com.json")
SHEET_ID    = "1rt-lQ6J0ysLDSocsqQw9ITMqVmG5vhZCC3sQmc4GlqI"
CLIENT_ID   = "1053367961810-tmo8k6gnb5tbohtkvnkdjgfn06cbmobj.apps.googleusercontent.com"
VENV_PYTHON = os.path.dirname(sys.executable)

# ── Args ─────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--dep",  default="ORY")
parser.add_argument("--arr",  default="RAI")
parser.add_argument("--out",  default="2026-05-06")
parser.add_argument("--ret",  default="2026-05-13")
parser.add_argument("--adults", type=int, default=1)
args = parser.parse_args()

URL_GF = (
    f"https://www.google.com/travel/flights?"
    f"hl=fr#flt={args.dep}.{args.arr}.{args.out}*{args.arr}.{args.dep}.{args.ret}"
    f";c:EUR;e:1;sd:1;t:f;tt:o"
)

# ── Google OAuth ──────────────────────────────────────────────────────────────
def get_access_token():
    with open(TOKEN_FILE) as f:
        tokens = json.load(f)
    data = json.dumps({
        "client_id": CLIENT_ID,
        "client_secret": tokens.get("client_secret", ""),
        "refresh_token": tokens["refresh_token"],
        "grant_type": "refresh_token"
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["access_token"]

def sheets_write(access, values):
    body = json.dumps({"values": values}).encode()
    req = urllib.request.Request(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/vols!A1?valueInputOption=RAW",
        data=body,
        headers={"Authorization": "Bearer " + access, "Content-Type": "application/json"},
        method="PUT"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read()).get("updatedRows", 0)

# ── Scraping via fast-flights ─────────────────────────────────────────────────
def fetch_flights():
    from fast_flights import Passengers, get_flights, FlightData
    print(f"  Scraping {args.dep}→{args.arr} {args.out}/{args.ret}...")
    result = get_flights(
        flight_data=[
            FlightData(date=args.out, from_airport=args.dep, to_airport=args.arr),
            FlightData(date=args.ret, from_airport=args.arr, to_airport=args.dep),
        ],
        trip="round-trip",
        passengers=Passengers(adults=args.adults),
        seat="economy",
        fetch_mode="local",
    )
    print(f"  → {len(result.flights)} vols bruts")
    return result

def parse_price(p):
    if p is None: return None
    s = str(p).replace("€","").replace("$","").replace(",","").strip()
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None

def parse_duration(d):
    if not d: return 0
    m = re.search(r"(\d+)\s*hr?\s*(\d+)?\s*min?", str(d))
    if m:
        h, mn = int(m.group(1)), int(m.group(2) or 0)
        return h * 60 + mn
    m2 = re.search(r"(\d+)\s*hr?", str(d))
    return int(m2.group(1)) * 60 if m2 else 0

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*55}")
    print(f"  Vols Tracker — {datetime.now():%d/%m/%Y %H:%M:%S}")
    print(f"  Route : {args.dep} → {args.arr} | {args.out} → {args.ret}")
    print(f"{'='*55}")

    result = fetch_flights()
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now().strftime("%d/%m")

    # Construire les lignes
    rows = [["rank","airline","code","dep","arr","depA","arrA",
             "dur","dur_min","stops","stop_txt","price","ret",
             "source","url","best","updated_at"]]

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
        stop_txt = "Direct" if stops == 0 else f"{stops} escale{'s' if stops>1 else ''}"

        rows.append([
            rank,
            str(f.name or ""),
            str(f.name or "")[:2].upper(),
            str(f.departure or ""),
            str(f.arrival or ""),
            args.dep, args.arr,
            dur_txt, dur_min,
            stops, stop_txt,
            price,
            "Aller-retour",
            f"Google Flights · {today}",
            URL_GF,
            "true" if rank == 1 else "false",
            now,
        ])

        if rank >= 15: break

    print(f"\n  {len(rows)-1} vols à enregistrer :")
    for r in rows[1:6]:
        print(f"    {r[1]:25} {r[3]}→{r[4]}  {r[7]:6}  {r[10]} esc.  {r[11]} €")

    # Écrire dans Google Sheets
    access = get_access_token()
    updated = sheets_write(access, rows)
    print(f"\n✓ Google Sheet mis à jour ({updated} lignes)")
    print(f"✓ URL : https://docs.google.com/spreadsheets/d/{SHEET_ID}")
    print(f"✓ Prix min : {rows[1][11]} € ({rows[1][1]})")
    print(f"✓ Terminé à {datetime.now():%H:%M:%S}\n")

if __name__ == "__main__":
    main()
