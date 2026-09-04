"""Add verified shop rows from imports/new_shops.json.

Each candidate is skipped when an open shop row already sits within 150 m
(same-place guard; the collector's own sync keys on osm_id, which manual
additions may not have). Prints one line per candidate.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import Supabase, get_all  # noqa: E402


def distance_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    rad = math.pi / 180
    d_lat = (b_lat - a_lat) * rad
    d_lng = (b_lng - a_lng) * rad
    h = math.sin(d_lat / 2) ** 2 + math.cos(a_lat * rad) * math.cos(b_lat * rad) * math.sin(d_lng / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def main() -> None:
    db = Supabase()
    with open("imports/new_shops.json") as handle:
        candidates = json.load(handle)
    existing = get_all(db, "shops", {"select": "*"})
    today = dt.date.today().isoformat()
    for row in candidates:
        note = row.pop("note", None)
        row["last_seen"] = today
        near = [s for s in existing if not s.get("closed_at") and s.get("lat") and distance_m(row["lat"], row["lng"], s["lat"], s["lng"]) < 150]
        if near:
            print(f"SKIP {row['name']} ({row['address']}): within 150m of shop {near[0]['id']} {near[0]['name']}")
            continue
        created = db.post("shops", row)[0]
        print(f"ADDED shop {created['id']}: {row['name']} ({row['address']})" + (f" - {note}" if note else ""))


if __name__ == "__main__":
    main()
