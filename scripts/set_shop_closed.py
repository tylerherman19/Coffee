#!/usr/bin/env python3
"""Update shop fields: closed_at, address, and/or name.

Usage:
  python scripts/set_shop_closed.py --shop-id 198 [--closed-on 2026-09-04]
  python scripts/set_shop_closed.py --shop-id 198 --reopen
  python scripts/set_shop_closed.py --shop-id 486 --address "800 LaSalle Avenue, Minneapolis, MN"
  python scripts/set_shop_closed.py --shop-id 142 --name "41Fork Exchange at Wantable Cafe"
"""

from __future__ import annotations

import argparse
import datetime as dt

from collect import Supabase


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop-id", type=int, required=True)
    parser.add_argument("--closed-on", default="", help="YYYY-MM-DD (blank = today when no other field is given)")
    parser.add_argument("--reopen", action="store_true", help="Clear closed_at")
    parser.add_argument("--address", default="", help="Set the shop address")
    parser.add_argument("--name", default="", help="Set the shop name")
    args = parser.parse_args()

    values: dict = {}
    if args.reopen:
        values["closed_at"] = None
    elif args.closed_on or (not args.address and not args.name):
        values["closed_at"] = args.closed_on or dt.date.today().isoformat()
    if args.address:
        values["address"] = args.address
    if args.name:
        values["name"] = args.name

    sb = Supabase()
    rows = sb.get("shops", {"id": f"eq.{args.shop_id}", "select": "id,name,address,closed_at,scrape_status"})
    if not rows:
        raise SystemExit(f"shop {args.shop_id} not found")
    print(f"before: {rows[0]}")

    sb.patch("shops", f"id=eq.{args.shop_id}", values)

    rows = sb.get("shops", {"id": f"eq.{args.shop_id}", "select": "id,name,address,closed_at,scrape_status"})
    print(f"after: {rows[0]}")


if __name__ == "__main__":
    main()
