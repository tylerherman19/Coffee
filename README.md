# Coffee Prices

A mobile-first public guide to direct-menu coffee and food prices in Milwaukee and the Twin Cities.

## What it does

- Discovers cafes from OpenStreetMap in both metros.
- Finds direct Square, Toast, SpotOn, ChowNow, Incentivio, and Kyoo ordering
  pages, from the shop's own site or - for the shops that link no ordering page,
  and the third with no website at all - by matching the shop against the
  platform's own location directory.
- Reads each platform through its public, unauthenticated read API rather than
  its markup: Toast's GraphQL gateway, SpotOn's server-rendered page data,
  Incentivio's catalogue service, and Kyoo's published Square catalogue. See
  `scripts/menu_sources.py`.
- Falls back to the shop's own website when there is no ordering platform,
  reading drink prices out of plain HTML two levels in from the homepage.
- ChowNow is white-label ordering that bills the shop, not a delivery
  marketplace, but chownow.com answers 403 to every host and path from a
  datacenter IP, so the collector records the platform and those menus arrive as
  staged captures.
- Records append-only price observations and changes in Supabase.
- Separates explicit drink sizes from inferred sizes.
- Publishes shop menus, drink comparisons, ratings when available, and a detailed OpenStreetMap view.
- Does not collect Uber Eats, DoorDash, or Grubhub prices.

## Collection

The `Collect coffee prices` GitHub Action runs at 00:30 UTC each day and can also run manually. It uses a service-side Supabase key. The public site receives only the publishable key and has read-only RLS access.

`Collect platform menus` (`scripts/collect_menus.py`) runs the same collection
path against a narrower target - the shops with no menu, a thin one, or a stale
one - weekly and on demand, with `--dry-run`, `--metro`, `--platform`,
`--shop-id` and `--limit`. It also runs a single ordering URL with no database
at all, which is how a scraper is checked against the live source:

```
python scripts/collect_menus.py --url https://order.incentivio.com/c/anodynecoffee
python scripts/collect_menus.py --url https://order.spoton.com/... --emit imports/name.json
python scripts/collect_menus.py --directory milwaukee
```

OpenStreetMap-derived locations are displayed with the required OpenStreetMap attribution.
