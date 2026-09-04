#!/usr/bin/env python3
"""Set or clear a shop's closed_at date.

Usage:
  python scripts/set_shop_closed.py --shop-id 198 [--closed-on 2026-09-04]
  python scripts/set_shop_closed.py --shop-id 198 --reopen
"""

from __future__ import annotations

import argparse
import datetime as dt

from collect import Supabase


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop-id", type=int, required=True)
    parser.add_argument("--closed-on", default="", help="YYYY-MM-DD (blank = today)")
    parser.add_argument("--reopen", action="store_true", help="Clear closed_at")
    args = parser.parse_args()

    closed_at = None if args.reopen else (args.closed_on or dt.date.today().isoformat())

    sb = Supabase()
    rows = sb.get("shops", {"id": f"eq.{args.shop_id}", "select": "id,name,closed_at,scrape_status"})
    if not rows:
        raise SystemExit(f"shop {args.shop_id} not found")
    shop = rows[0]
    print(f"before: {shop}")

    sb.patch("shops", f"id=eq.{args.shop_id}", {"closed_at": closed_at})

    rows = sb.get("shops", {"id": f"eq.{args.shop_id}", "select": "id,name,closed_at,scrape_status"})
    print(f"after: {rows[0]}")


if __name__ == "__main__":
    main()
