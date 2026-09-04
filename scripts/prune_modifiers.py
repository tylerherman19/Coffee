#!/usr/bin/env python3
"""Delete specific modifier choice rows for a shop (stale-capture cleanup).

Usage:
  python scripts/prune_modifiers.py --shop-id 364 --group "Smoothie Size" --choices "OZ (regular),OZ (large)"
"""

from __future__ import annotations

import argparse

import requests

from collect import Supabase


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop-id", type=int, required=True)
    parser.add_argument("--group", required=True, help="Modifier group_name")
    parser.add_argument("--choices", required=True, help="Comma-separated choice_name values")
    args = parser.parse_args()

    choices = [c.strip() for c in args.choices.split(",") if c.strip()]
    if not choices:
        raise SystemExit("no choices given")

    sb = Supabase()
    items = sb.get("items", {"shop_id": f"eq.{args.shop_id}", "select": "id"})
    item_ids = [str(i["id"]) for i in items]
    if not item_ids:
        raise SystemExit(f"no items for shop {args.shop_id}")

    in_list = "(" + ",".join(item_ids) + ")"
    existing = sb.get("modifiers", {"item_id": f"in.{in_list}", "group_name": f"eq.{args.group}", "select": "id,item_id,choice_name"})
    targets = [m for m in existing if m["choice_name"] in choices]
    print(f"found {len(targets)} modifier rows to delete")

    for m in targets:
        response = requests.delete(f"{sb.url}/rest/v1/modifiers?id=eq.{m['id']}", headers=sb.headers, timeout=30)
        response.raise_for_status()
    print(f"deleted {len(targets)}")


if __name__ == "__main__":
    main()
