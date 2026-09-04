#!/usr/bin/env python3
"""Import a manually captured menu bundle (imports/<name>.json) into Supabase.

Manual captures are staged as JSON and checked into the repo (see
imports/README.md for the bundle format). This script reuses the collector's
own Supabase client and classification helpers, and mirrors collect.save_menu's
write semantics (items upserted by platform_item_id, observations rows with
price_channel "direct" driving current_price_cents via trigger, modifiers rows
with group_name + choice_name + price_delta_cents) so the format cannot drift.

Usage: python scripts/import_menu.py imports/<name>.json [--dry-run]
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import requests

from collect import Supabase, classify_name, parse_size


def write(fn, *args):
    # Run a Supabase write, surfacing the response body on failure.
    try:
        return fn(*args)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        body = exc.response.text[:500] if exc.response is not None else "<no response>"
        raise RuntimeError(f"Supabase write failed ({status}): {body}") from exc

BATCH = 400


def chunked(rows: list[dict[str, Any]], size: int = BATCH) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def import_bundle(db: Supabase, bundle: dict[str, Any], dry_run: bool = False) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    today = dt.date.today().isoformat()
    items = bundle.get("items") or []
    if not items:
        raise SystemExit("bundle has no items")
    # A menu can list the same platform item under two categories; the
    # (shop_id, platform_item_id) key is unique, so collapse duplicates
    # (last wins, matching the collector's html extractor).
    by_pid = {entry["platform_item_id"]: entry for entry in items}
    if len(by_pid) != len(items):
        print(f"note: collapsed {len(items) - len(by_pid)} duplicate platform_item_id rows (last wins)")
        items = list(by_pid.values())
    source_url = bundle.get("source_url")
    platform = bundle.get("platform")
    bundle_raw = bundle.get("raw") or {}

    for shop in bundle["shops"]:
        shop_id = shop["id"]
        label = shop.get("slug") or str(shop_id)
        status = "collected" if items else "empty"
        shop_patch: dict[str, Any] = {"last_checked_at": now, "scrape_status": status}
        if platform:
            shop_patch["platform"] = platform
        existing = db.get("items", {"select": "*", "shop_id": f"eq.{shop_id}"})
        by_platform = {item["platform_item_id"]: item for item in existing}

        new_rows: list[dict[str, Any]] = []
        new_entries: list[dict[str, Any]] = []
        changed_obs: list[dict[str, Any]] = []
        unchanged_ids: list[int] = []
        seen: set[str] = set()

        for entry in items:
            pid = entry["platform_item_id"]
            seen.add(pid)
            is_drink, drink_type = classify_name(entry["name"], entry.get("category"))
            size_label, size_oz, confidence = parse_size(entry["name"])
            values = {
                "name": entry["name"],
                "category": entry.get("category"),
                "is_drink": is_drink,
                "drink_type": drink_type,
                "size_label": size_label,
                "size_oz": size_oz,
                "size_confidence": confidence,
                "last_seen": today,
                "removed_at": None,
            }
            item = by_platform.get(pid)
            obs = {
                "observed_at": now,
                "price_cents": entry["price_cents"],
                "price_low_cents": entry.get("price_low_cents"),
                "price_high_cents": entry.get("price_high_cents"),
                "price_channel": "direct",
                "available": entry.get("available", True),
                "source_url": source_url,
                "raw": {**bundle_raw, **(entry.get("raw") or {}), "shop": label},
            }
            if item is None:
                new_rows.append({**values, "shop_id": shop_id, "platform_item_id": pid})
                new_entries.append({**obs, "_pid": pid, "_entry": entry})
            elif item.get("current_price_cents") != entry["price_cents"]:
                changed_obs.append({**obs, "item_id": item["id"], "_entry": entry})
                if not dry_run:
                    write(db.patch, "items", f"id=eq.{item['id']}", values)
            else:
                unchanged_ids.append(item["id"])

        id_by_pid: dict[str, int] = {}
        if not dry_run:
            try:
                write(db.patch, "shops", f"id=eq.{shop_id}", shop_patch)
            except RuntimeError as exc:
                if "platform" in shop_patch:
                    print(f"shop {shop_id}: platform value rejected ({exc}); retrying without platform")
                    shop_patch.pop("platform", None)
                    write(db.patch, "shops", f"id=eq.{shop_id}", shop_patch)
                else:
                    raise
            for batch in chunked(new_rows):
                for created in write(db.post, "items", batch):
                    id_by_pid[created["platform_item_id"]] = created["id"]
            def clean(obs: dict[str, Any]) -> dict[str, Any]:
                return {k: v for k, v in obs.items() if not k.startswith("_")}
            obs_rows = [{**clean(obs), "item_id": id_by_pid[obs["_pid"]]} for obs in new_entries]
            obs_rows += [clean(obs) for obs in changed_obs]
            for batch in chunked(obs_rows):
                write(db.post, "observations", batch)
            if unchanged_ids:
                ids = ",".join(str(i) for i in unchanged_ids)
                write(db.patch, "items", f"id=in.({ids})", {"last_checked_at": now, "last_seen": today})
            removed = [item["id"] for item in existing if item["platform_item_id"] not in seen and not item.get("removed_at")]
            if removed:
                ids = ",".join(str(i) for i in removed)
                write(db.patch, "items", f"id=in.({ids})", {"removed_at": today})

            # Modifiers: keep only rows not already latest for the item.
            mod_rows: list[dict[str, Any]] = []
            item_ids = {**{e["_pid"]: id_by_pid.get(e["_pid"]) for e in new_entries},
                        **{item["platform_item_id"]: item["id"] for item in existing}}
            for entry in items:
                item_id = item_ids.get(entry["platform_item_id"])
                if item_id is None or not entry.get("modifiers"):
                    continue
                prior = db.get("modifiers", {"select": "group_name,choice_name,price_delta_cents", "item_id": f"eq.{item_id}", "order": "observed_at.desc", "limit": "100"})
                latest = {(row.get("group_name"), row["choice_name"], row["price_delta_cents"]) for row in prior}
                for mod in entry["modifiers"]:
                    key = (mod.get("group_name"), mod["choice_name"], mod["price_delta_cents"])
                    if key not in latest:
                        mod_rows.append({"item_id": item_id, "group_name": mod.get("group_name"), "choice_name": mod["choice_name"], "price_delta_cents": mod["price_delta_cents"], "observed_at": now})
            for batch in chunked(mod_rows):
                write(db.post, "modifiers", batch)
            print(f"shop {shop_id} ({label}): {len(new_rows)} new, {len(changed_obs)} price changes, {len(unchanged_ids)} unchanged, {len(mod_rows)} modifiers, {len(removed) if not dry_run else 0} removed")
        else:
            removed = [item for item in existing if item["platform_item_id"] not in seen and not item.get("removed_at")]
            mod_count = sum(len(e.get("modifiers") or []) for e in items)
            print(f"[dry-run] shop {shop_id} ({label}): {len(existing)} existing, {len(new_rows)} new, {len(changed_obs)} price changes, {len(unchanged_ids)} unchanged, {mod_count} modifier candidates, {len(removed)} would be removed")


def main() -> None:
    args = [arg for arg in sys.argv[1:] if arg != "--dry-run"]
    dry_run = "--dry-run" in sys.argv
    if not args:
        raise SystemExit("usage: python scripts/import_menu.py imports/<name>.json [--dry-run]")
    path = Path(args[0])
    if path.parts[0] != "imports" or not path.is_file():
        raise SystemExit(f"import file must live under imports/: {path}")
    bundle = json.loads(path.read_text())
    db = Supabase()
    import_bundle(db, bundle, dry_run=dry_run)
    print("Import complete" if not dry_run else "Dry run complete (no writes)")


if __name__ == "__main__":
    main()
