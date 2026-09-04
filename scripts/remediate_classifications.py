"""One-shot reclassification sweep over the items table.

Recomputes (is_drink, drink_type) for every item with the collector's own
refine_classification() - the same function the collector and the staged
importer write through - so the three paths cannot drift and a fresh
collection cannot re-introduce rows this sweep removes.

Rows are only updated when the verdict changes. Prints a before/after tally.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import Supabase, get_all, refine_classification  # noqa: E402


def main() -> None:
    db = Supabase()
    items = get_all(db, "items", {
        "select": "id,name,category,is_drink,drink_type,current_price_cents,size_oz,removed_at",
        "order": "id.asc",
    })
    changes: dict[tuple[bool, str | None], list[int]] = {}
    tally = {"stripped": 0, "retype": 0, "backfill_drink": 0}
    for item in items:
        new = refine_classification(
            item["name"], item.get("category"), item.get("current_price_cents"), item.get("size_oz")
        )
        old = (bool(item["is_drink"]), item.get("drink_type"))
        if old == new:
            continue
        changes.setdefault(new, []).append(item["id"])
        if old[0] and not new[0]:
            tally["stripped"] += 1
        elif old[0] and new[0]:
            tally["retype"] += 1
        else:
            tally["backfill_drink"] += 1
    print(f"scanned {len(items)} items; {sum(len(v) for v in changes.values())} rows change")
    for (is_drink, drink_type), ids in sorted(changes.items(), key=lambda kv: -len(kv[1])):
        print(f"  -> is_drink={is_drink} drink_type={drink_type}: {len(ids)} rows")
        for i in range(0, len(ids), 200):
            db.patch("items", f"id=in.({','.join(str(x) for x in ids[i:i + 200])})", {"is_drink": is_drink, "drink_type": drink_type})
    print(f"tally: {tally}")


if __name__ == "__main__":
    main()
