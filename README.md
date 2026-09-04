# Coffee Prices

A mobile-first public guide to direct-menu coffee and food prices in Milwaukee and the Twin Cities.

## What it does

- Discovers cafes from OpenStreetMap in both metros.
- Finds direct Square, Toast, SpotOn, and ChowNow ordering pages. ChowNow is
  white-label ordering that bills the shop, not a delivery marketplace, but it
  serves a Cloudflare bot challenge that answers 403 to a datacenter IP, so the
  collector records the platform and those menus arrive as staged captures.
- Records append-only price observations and changes in Supabase.
- Separates explicit drink sizes from inferred sizes.
- Publishes shop menus, drink comparisons, ratings when available, and a detailed OpenStreetMap view.
- Does not collect Uber Eats, DoorDash, or Grubhub prices.

## Collection

The `Collect coffee prices` GitHub Action runs at 00:30 UTC each day and can also run manually. It uses a service-side Supabase key. The public site receives only the publishable key and has read-only RLS access.

OpenStreetMap-derived locations are displayed with the required OpenStreetMap attribution.
