"""Shop-row cleanup (audit finding 6):
- rename shop 218 to SweeDee Cafe (OSM still carries the prior tenant's name)
- retire duplicate shop rows: Spyhouse 602 (identical coords + identical
  113-item catalog to 601) and Five Watt 523 (same street address as 253)
- backfill placeholder addresses from data/address_fixes.json (reverse-geocoded
  from each shop's own coordinates)
- retire exact duplicate item rows: same shop, name, size and price on two
  live rows -> keep the oldest, removed_at the rest
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import Supabase  # noqa: E402

today = dt.date.today().isoformat()
now = dt.datetime.now(dt.timezone.utc).isoformat()


def main() -> None:
    db = Supabase()

    db.patch("shops", "id=eq.218", {"name": "SweeDee Cafe"})
    print("shop 218 renamed to SweeDee Cafe")

    for dup, keep in ((602, 601), (523, 253)):
        items = db.get("items", {"select": "id", "shop_id": f"eq.{dup}", "removed_at": "is.null", "limit": "1000"})
        if items:
            ids = ",".join(str(i["id"]) for i in items)
            db.patch("items", f"id=in.({ids})", {"removed_at": today})
        db.patch("shops", f"id=eq.{dup}", {"closed_at": now})
        print(f"shop {dup} retired ({len(items)} items removed); {keep} is the surviving row")

    fixes = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "address_fixes.json")))
    n = 0
    for fix in fixes:
        if fix.get("address"):
            db.patch("shops", f"id=eq.{fix['id']}", {"address": fix["address"]})
            n += 1
    print(f"{n} placeholder addresses backfilled")

    # exact duplicate live items: same shop+name+size+price
    dupes = 0
    shops = db.get("shops", {"select": "id", "closed_at": "is.null", "limit": "1000"})
    for shop in shops:
        items = db.get("items", {"select": "id,name,size_label,current_price_cents", "shop_id": f"eq.{shop['id']}", "removed_at": "is.null", "order": "id.asc", "limit": "1000"})
        seen: dict[tuple, int] = {}
        drop: list[int] = []
        for item in items:
            key = (item["name"], item.get("size_label"), item.get("current_price_cents"))
            if key in seen:
                drop.append(item["id"])
            else:
                seen[key] = item["id"]
        if drop:
            db.patch("items", f"id=in.({','.join(str(i) for i in drop)})", {"removed_at": today})
            dupes += len(drop)
            print(f"shop {shop['id']}: {len(drop)} duplicate item rows retired")
    print(f"{dupes} duplicate item rows retired total")


if __name__ == "__main__":
    main()
