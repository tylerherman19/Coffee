# Staged manual menu captures

Used for menus the collector cannot read itself: a shop on an ordering
platform with no reachable catalogue (ChowNow answers 403 to the runner), a
PDF-only menu, or a chain whose prices are not published per location.

Each `imports/<name>.json` is one manually captured menu bundle, imported into
Supabase by the **Import staged menu** workflow (`.github/workflows/import.yml`,
workflow_dispatch, input: path to the bundle). The importer
(`scripts/import_menu.py`) reuses the collector's write logic, so bundles must
match this schema:

```json
{
  "platform": "colectivo",                  // optional; patched onto each shop
  "source_url": "https://... (how/where captured)",
  "shops": [{"id": 144, "slug": "colectivo-foundry"}],
  "items": [
    {
      "platform_item_id": "brewed-coffee",  // stable per-shop upsert key
      "name": "Brewed Coffee",
      "category": "Coffee",
      "price_cents": 335,
      "price_low_cents": 285,               // optional size range
      "price_high_cents": 370,
      "available": true,
      "raw": {"source": "..."},             // optional, stored on observation
      "modifiers": [                        // optional
        {"group_name": "Milk Choice", "choice_name": "Oat Milk", "price_delta_cents": 0}
      ]
    }
  ]
}
```

Semantics mirror `collect.save_menu`: items are upserted by
`platform_item_id` per shop; an `observations` row with `price_channel:
"direct"` is inserted for new items and price changes (drives
`current_price_cents` via trigger); modifiers are appended only when the
(group, choice, delta) triple is not already the latest for the item; items
missing from the bundle are marked `removed_at`. Every shop in `shops` gets
the full `items` list and `scrape_status: "collected"`.
