"""One-shot reclassification sweep over the items table.

Recomputes (is_drink, drink_type) for every live item with the collector's
own classify_name() so the logic cannot drift, plus one price-aware retail
guard the classifier cannot express (it never sees prices):
  price >= $10 in a retail-ish category (retail / supplies / theory) is a
  bag of beans or gear, not a cup.
Rows are only updated when the verdict changes. Prints a before/after tally.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import Supabase, classify_name  # noqa: E402

import re  # noqa: E402

RETAIL_PRICE_GUARD = re.compile(r"retail|supplies|theory", re.I)


def all_items(db: Supabase) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = db.get("items", {
            "select": "id,name,category,is_drink,drink_type,current_price_cents,removed_at",
            "order": "id.asc", "offset": str(offset), "limit": "1000",
        })
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


def main() -> None:
    db = Supabase()
    items = all_items(db)
    changes: dict[tuple[bool, str | None], list[int]] = {}
    tally = {"category_strip": 0, "retail_bag_strip": 0, "retype": 0, "backfill_drink": 0}
    drip_priced_10 = 0
    for item in items:
        is_drink, drink_type = classify_name(item["name"], item.get("category"))
        price = item.get("current_price_cents")
        if is_drink and price is not None and price >= 1000 and item.get("category") and RETAIL_PRICE_GUARD.search(item["category"]):
            is_drink, drink_type = False, None
        old = (bool(item["is_drink"]), item.get("drink_type"))
        new = (is_drink, drink_type)
        if old == new:
            continue
        changes.setdefault(new, []).append(item["id"])
        if old[0] and not new[0]:
            if old[1] == "drip" and (price or 0) >= 1000:
                drip_priced_10 += 1
                tally["retail_bag_strip"] += 1
            else:
                tally["category_strip"] += 1
        elif old[0] and new[0]:
            tally["retype"] += 1
        elif not old[0] and new[0]:
            tally["backfill_drink"] += 1
    print(f"scanned {len(items)} items; {sum(len(v) for v in changes.values())} rows change")
    for (is_drink, drink_type), ids in sorted(changes.items(), key=lambda kv: -len(kv[1])):
        print(f"  -> is_drink={is_drink} drink_type={drink_type}: {len(ids)} rows")
        for i in range(0, len(ids), 200):
            db.patch("items", f"id=in.({','.join(str(x) for x in ids[i:i+200])})", {"is_drink": is_drink, "drink_type": drink_type})
    print(f"tally: {tally}; priced-drip->retail refills: {drip_priced_10}")


if __name__ == "__main__":
    main()
