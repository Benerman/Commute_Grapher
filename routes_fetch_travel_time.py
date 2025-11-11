import os, sqlite3
import requests
from dotenv import load_dotenv
import json, time, uuid
from datetime import datetime

load_dotenv()

API_KEY = os.environ["GOOGLE_MAPS_API_KEY"]

ORIGIN_LABEL = os.environ["ORIGIN_LABEL"]
ORIGIN_ADDRESS = os.environ["ORIGIN_ADDRESS"]
DEST_LABEL = os.environ["DEST_LABEL"]
DEST_ADDRESS = os.environ["DEST_ADDRESS"]

DB = "commute.db"
PROVIDER = "google"

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def get_db():
    # default isolation uses implicit transactions; we'll manage with context manager
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

    # distance
    meters = route.get("distanceMeters")
    miles_text = route["localizedValues"]["distance"]["text"]  # e.g., "12.3 mi"
    # duration
    duration_seconds_str = route["duration"]                    # e.g., "1532s"
    duration_static_text = route["localizedValues"]["staticDuration"]["text"]  # "25 min"
    duration_minutes_text = route["localizedValues"]["duration"]["text"]       # "28 min"

    # parse localized strings safely (handles "min" / "mins")
    def _to_int_minutes(s: str) -> int:
        return int(s.split()[0].replace(",", ""))

    output = {
        "description": description,
        "meters": int(meters),
        "miles": float(miles_text.split()[0].replace(",", "")),
        "duration_seconds": int(duration_seconds_str.rstrip("s")),
        "duration_static": _to_int_minutes(duration_static_text),
        "duration_minutes": _to_int_minutes(duration_minutes_text),
    }
    return output


def fetch_directions(o_lat, o_lon, d_lat, d_lon):
    body = {
        "origin": {"location": {"latLng": {"latitude": float(o_lat), "longitude": float(o_lon)}}},
        "destination": {"location": {"latLng": {"latitude": float(d_lat), "longitude": float(d_lon)}}},
        "travelMode": "DRIVE",
        "units": "IMPERIAL",
        "computeAlternativeRoutes": True,
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
        # "departureTime": {"seconds": int(time.time())}
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

    results = []
    for route in data["routes"]:
        results.append(_extract_route_info(route))
    return results


def main():
    o_lat, o_lon = fetch_coords(ORIGIN_LABEL, ORIGIN_ADDRESS)
    d_lat, d_lon = fetch_coords(DEST_LABEL, DEST_ADDRESS)

    results = fetch_directions(o_lat, o_lon, d_lat, d_lon)

    # ---- Atomic batch insert (all-or-nothing) ----
    batch_id = uuid.uuid4().hex
    # Fixed per-run timestamp (ISO seconds precision for readability & grouping)
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
        with con:  # single transaction; commit once; rollback on any error
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

    for r in results:
        print(
            f"[{batch_id}] Logged route: {r['description']} - {r['duration_minutes']} min, "
            f"{r['meters']/1000:.1f} km / {r['miles']} mi"
        )

if __name__ == "__main__":
    main()
