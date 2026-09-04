#!/usr/bin/env python3
"""Backfill shop.neighborhood from a staged JSON file.

Usage: python scripts/set_neighborhoods.py [data/neighborhoods.json] [--dry-run]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from collect import Supabase


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv
    path = Path(args[0] if args else "data/neighborhoods.json")
    updates = json.loads(path.read_text())["updates"]

    by_hood: dict[str, list[int]] = defaultdict(list)
    for update in updates:
        hood = update.get("neighborhood")
        if hood:
            by_hood[hood].append(update["id"])

    sb = Supabase()
    done = 0
    for hood, ids in sorted(by_hood.items()):
        for i in range(0, len(ids), 100):
            chunk = ",".join(str(x) for x in ids[i : i + 100])
            if not dry_run:
                sb.patch("shops", f"id=in.({chunk})", {"neighborhood": hood})
            done += len(chunk)
    print(f"{'[dry-run] ' if dry_run else ''}set neighborhood on {done} shops across {len(by_hood)} neighborhoods")


if __name__ == "__main__":
    main()
