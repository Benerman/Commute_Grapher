# route_fetch_travel_time.py
import os, sqlite3
import requests
from dotenv import load_dotenv
import json, uuid
from datetime import datetime, time as dtime
try:
    from zoneinfo import ZoneInfo  # Py>=3.9
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

load_dotenv()

API_KEY = os.environ["GOOGLE_MAPS_API_KEY"]

# Define both endpoints up front
HOME_LABEL   = os.environ["HOME_LABEL"]
HOME_ADDRESS = os.environ["HOME_ADDRESS"]
WORK_LABEL   = os.environ["WORK_LABEL"]
WORK_ADDRESS = os.environ["WORK_ADDRESS"]

# Optional timezone; defaults to America/New_York
LOCAL_TZ = os.getenv("LOCAL_TZ", "America/New_York")

DB = "commute.db"
PROVIDER = "google"

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def get_db():
    return sqlite3.connect(DB)


def fetch_coords(label: str, address: str):
    """Resolve and cache lat/lon for a label+address using Google Geocoding."""
    con = get_db()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT lat, lon FROM locations WHERE label=?", (label,))
    row = cur.fetchone()
    if row and row["lat"] is not None and row["lon"] is not None:
        con.close()
        return row["lat"], row["lon"]

    r = requests.get(GEOCODE_URL, params={"address": address, "key": API_KEY}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK" or not data.get("results"):
        raise RuntimeError(f"Geocode failed for '{label}': {data.get('status')}")

    loc = data["results"][0]["geometry"]["location"]
    lat, lon = float(loc["lat"]), float(loc["lng"])

    cur.execute(
        """
        INSERT INTO locations(label, address, lat, lon)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(label) DO UPDATE SET address=excluded.address, lat=excluded.lat, lon=excluded.lon
        """,
        (label, address, lat, lon),
    )
    con.commit()
    con.close()
    return lat, lon


def _extract_route_info(route):
    description = route["description"]
    meters = int(route.get("distanceMeters"))
    miles_text = route["localizedValues"]["distance"]["text"]          # "12.3 mi"
    duration_seconds_str = route["duration"]                           # "1532s"
    duration_static_text = route["localizedValues"]["staticDuration"]["text"]  # "25 min"
    duration_minutes_text = route["localizedValues"]["duration"]["text"]       # "28 min"

    def _to_int_minutes(s: str) -> int:
        return int(s.split()[0].replace(",", ""))

    return {
        "description": description,
        "meters": meters,
        "miles": float(miles_text.split()[0].replace(",", "")),
        "duration_seconds": int(duration_seconds_str.rstrip("s")),
        "duration_static": _to_int_minutes(duration_static_text),
        "duration_minutes": _to_int_minutes(duration_minutes_text),
    }


def fetch_directions(o_lat, o_lon, d_lat, d_lon):
    body = {
        "origin": {"location": {"latLng": {"latitude": float(o_lat), "longitude": float(o_lon)}}},
        "destination": {"location": {"latLng": {"latitude": float(d_lat), "longitude": float(d_lon)}}},
        "travelMode": "DRIVE",
        "units": "IMPERIAL",
        "computeAlternativeRoutes": True,
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
    }
    headers = {
        "X-Goog-Api-Key": API_KEY,
        "Content-Type": "application/json",
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.localizedValues,routes.description",
    }

    r = requests.post(ROUTES_URL, headers=headers, json=body, timeout=25)
    if not r.ok:
        try:
            body_text = r.json()
        except ValueError:
            body_text = r.text
        raise RuntimeError(
            f"Routes API returned {r.status_code}\nheaders: {dict(r.headers)}\nbody: {body_text}\n\n"
            "Check: API enabled, billing active, and key permissions."
        )

    data = r.json()
    if not data.get("routes"):
        raise RuntimeError(f"Routes API failed: no routes returned - {data}")

    return [_extract_route_info(rt) for rt in data["routes"]]


def _now_local():
    return datetime.now(ZoneInfo(LOCAL_TZ))


def _in_window(now_t: datetime, start: dtime, end: dtime) -> bool:
    """True if local time is within [start, end]; assumes same-day window (no overnight)."""
    t = now_t.time()
    return (t >= start) and (t <= end)


def choose_direction():
    """
    Windows (local time):
      - 05:30–10:30 → Home -> Work
      - 10:40–18:30 → Work -> Home
    Outside those windows: no request is made (exit cleanly).
    Override:
      - DIRECTION=H2W or W2H to force a direction regardless of time.
    """
    override = os.getenv("DIRECTION", "").upper().strip()
    if override in {"H2W", "W2H"}:
        return ("HOME", "WORK") if override == "H2W" else ("WORK", "HOME")

    now = _now_local()
    if _in_window(now, dtime(5, 30), dtime(10, 30)):
        return ("HOME", "WORK")
    if _in_window(now, dtime(10, 40), dtime(18, 30)):
        return ("WORK", "HOME")

    return (None, None)  # outside windows


def main():
    src, dst = choose_direction()
    if src is None:
        print("Outside configured commute windows; no request made.")
        return

    if src == "HOME":
        ORIGIN_LABEL, ORIGIN_ADDRESS = HOME_LABEL, HOME_ADDRESS
        DEST_LABEL, DEST_ADDRESS = WORK_LABEL, WORK_ADDRESS
    else:
        ORIGIN_LABEL, ORIGIN_ADDRESS = WORK_LABEL, WORK_ADDRESS
        DEST_LABEL, DEST_ADDRESS = HOME_LABEL, HOME_ADDRESS

    o_lat, o_lon = fetch_coords(ORIGIN_LABEL, ORIGIN_ADDRESS)
    d_lat, d_lon = fetch_coords(DEST_LABEL, DEST_ADDRESS)

    results = fetch_directions(o_lat, o_lon, d_lat, d_lon)

    # Atomic batch insert (group all routes for this run)
    batch_id = uuid.uuid4().hex
    batch_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    rows = [
        (
            batch_id,
            batch_ts,
            ORIGIN_LABEL,
            DEST_LABEL,
            r["description"],
            r["meters"],
            r["miles"],
            r["duration_seconds"],
            r["duration_static"],
            r["duration_minutes"],
        )
        for r in results
    ]

    con = get_db()
    try:
        with con:
            con.executemany(
                """
                INSERT INTO travel_times(
                    batch_id, batch_ts, origin_label, dest_label, description,
                    meters, miles, duration_seconds, duration_static, duration_minutes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    finally:
        con.close()

    dir_str = f"{ORIGIN_LABEL} -> {DEST_LABEL}"
    for r in results:
        print(
            f"[{batch_id}] {dir_str}: {r['description']} | {r['duration_minutes']} min | "
            f"{r['meters']/1000:.1f} km / {r['miles']} mi"
        )


if __name__ == "__main__":
    main()
