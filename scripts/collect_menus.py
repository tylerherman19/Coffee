#!/usr/bin/env python3
"""Collect menus for the shops the daily run leaves unpriced, one platform at a time.

The daily collector (scripts/collect.py) walks every shop in both metros and
writes what it finds. This is the same collection path pointed at a narrower
target: the shops with no menu, a stale one, or one too thin to compare, plus a
mode that runs a single ordering URL with no database at all so a scraper can be
checked against the live source.

Nothing here re-implements the write path - rows go through collect.save_menu,
so the classifier, the size parser and the observation/modifier semantics are
the collector's own.

Usage:
  python scripts/collect_menus.py [--metro milwaukee] [--platform toast]
                                  [--shop-id 42] [--limit 50] [--stale-days 14]
                                  [--all] [--dry-run] [--workers 5]
  python scripts/collect_menus.py --url https://order.spoton.com/... [--emit imports/name.json]
  python scripts/collect_menus.py --directory milwaukee
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import menu_sources  # noqa: E402
from collect import (  # noqa: E402
    MenuItem, Supabase, classify_name, collect_source, extract_modifiers, get_all,
    parse_size, refine_classification, resolve_source, save_menu,
)

# A menu with fewer comparable drinks than this is thin enough to be worth
# re-collecting even though the shop already has rows.
THIN_DRINKS = 3
STALE_DAYS = 14


def drink_rows(menu: list[MenuItem]) -> int:
    return sum(1 for entry in menu if classify_name(entry.name, entry.category)[0])


def is_stale(shop: dict[str, Any], days: int) -> bool:
    checked = shop.get("last_checked_at")
    if not checked:
        return True
    try:
        seen = dt.datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (dt.datetime.now(dt.timezone.utc) - seen).days >= days


def needs_menu(shop: dict[str, Any], counts: dict[int, int], args: argparse.Namespace) -> bool:
    """Whether this shop is worth a collection pass right now."""
    if args.all:
        return True
    if shop.get("scrape_status") != "collected":
        return True
    if counts.get(shop["id"], 0) < THIN_DRINKS:
        return True
    return is_stale(shop, args.stale_days)


def drink_counts(db: Supabase) -> dict[int, int]:
    """Live drink rows per shop, so a shop with only pastries counts as thin."""
    counts: dict[int, int] = {}
    for item in get_all(db, "items", {"select": "shop_id,is_drink,removed_at"}):
        if item.get("is_drink") and not item.get("removed_at"):
            counts[item["shop_id"]] = counts.get(item["shop_id"], 0) + 1
    return counts


def report(shop: dict[str, Any], platform: str | None, source: str | None, menu: list[MenuItem]) -> str:
    label = f"{shop['name']} [{shop.get('id', '-')}]"
    if not menu:
        return f"  --  {label}: nothing ({platform or 'no platform'})"
    return f"  {len(menu):3d}  {label}: {drink_rows(menu)} drinks via {platform} {source or ''}".rstrip()


def bundle(shop: dict[str, Any] | None, platform: str | None, source: str | None, menu: list[MenuItem]) -> dict[str, Any]:
    """A staged bundle in the imports/ schema, for a menu worth checking in.

    Same shape scripts/import_menu.py reads, so a capture made here can be
    replayed later without the platform being reachable again.
    """
    items = []
    for entry in menu:
        item: dict[str, Any] = {
            "platform_item_id": entry.platform_id,
            "name": entry.name,
            "category": entry.category,
            "price_cents": entry.price_cents,
            "price_low_cents": entry.low_cents,
            "price_high_cents": entry.high_cents,
            "available": True,
            "raw": entry.raw or {},
        }
        modifiers = [{"group_name": group, "choice_name": choice, "price_delta_cents": delta}
                     for group, choice, delta in extract_modifiers(entry.raw)]
        if modifiers:
            item["modifiers"] = modifiers
        items.append(item)
    shops = [{"id": shop["id"], "slug": shop.get("slug") or shop["name"]}] if shop else []
    return {"platform": platform, "source_url": source, "shops": shops, "items": items}


def run_url(args: argparse.Namespace) -> None:
    """Collect one ordering URL with no database, for checking a scraper."""
    platform = menu_sources.platform_of(args.url) or args.platform
    if not platform:
        raise SystemExit(f"no known platform for {args.url}; pass --platform")
    menu = menu_sources.extract(platform, args.url, args.location)
    print(f"{platform}: {len(menu)} items, {drink_rows(menu)} comparable drinks")
    for entry in sorted(menu, key=lambda item: item.name)[: args.limit or 40]:
        size_label, size_oz, _ = parse_size(entry.name)
        is_drink, drink_type = refine_classification(entry.name, entry.category, entry.price_cents, size_oz)
        kind = drink_type if is_drink else "-"
        print(f"  {entry.price_cents / 100:7.2f}  {kind:14s} {entry.name[:60]:62s} {entry.category or ''}")
    if args.emit:
        path = Path(args.emit)
        if path.parts[0] != "imports":
            raise SystemExit(f"staged bundles live under imports/: {path}")
        path.write_text(json.dumps(bundle(None, platform, args.url, menu), indent=1) + "\n")
        print(f"wrote {path} ({len(menu)} items); add the shop ids before importing")


def run_directory(metro: str) -> None:
    """Print a platform directory, to check what a shop would be matched against."""
    for listing in sorted(menu_sources.toast_directory(metro), key=lambda row: row["name"]):
        location = listing.get("location") or {}
        print(f"  {listing['guid']}  {listing['name'][:48]:50s} {location.get('address1') or ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metro", choices=sorted(menu_sources.METROS))
    parser.add_argument("--platform", help="only shops resolving to this platform")
    parser.add_argument("--shop-id", type=int, action="append", dest="shop_ids")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many shops")
    parser.add_argument("--stale-days", type=int, default=STALE_DAYS)
    parser.add_argument("--all", action="store_true", help="every shop, not just the unpriced ones")
    parser.add_argument("--dry-run", action="store_true", help="collect and report, write nothing")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--url", help="collect one ordering URL and print it; no database")
    parser.add_argument("--location", help="platform location/store id, when a merchant has several")
    parser.add_argument("--emit", help="write the --url result as a staged bundle under imports/")
    parser.add_argument("--directory", choices=sorted(menu_sources.METROS), help="print a platform directory")
    args = parser.parse_args()

    if args.url:
        return run_url(args)
    if args.directory:
        return run_directory(args.directory)

    db = Supabase()
    shops = get_all(db, "shops", {"select": "*", "closed_at": "is.null"})
    if args.metro:
        shops = [shop for shop in shops if shop.get("metro") == args.metro]
    if args.shop_ids:
        targets = [shop for shop in shops if shop["id"] in set(args.shop_ids)]
    else:
        counts = drink_counts(db)
        targets = [shop for shop in shops if needs_menu(shop, counts, args)]
    if args.platform:
        targets = [shop for shop in targets if resolve_source(shop)[0] == args.platform]
    if args.limit:
        targets = targets[: args.limit]
    print(f"{len(targets)} of {len(shops)} shops to collect"
          f"{' (dry run)' if args.dry_run else ''}")

    collected = items = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(collect_source, shop) for shop in targets]
        for future in concurrent.futures.as_completed(futures):
            shop, platform, source, menu, rating = future.result()
            print(report(shop, platform, source, menu))
            if menu:
                collected += 1
                items += len(menu)
            if not args.dry_run:
                save_menu(db, shop, platform, source, menu, rating)
    print(f"{collected} shops collected, {items} rows{' (nothing written)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
