# Coffee Prices

A mobile-first public guide to direct-menu coffee and food prices in Milwaukee and the Twin Cities.

## What it does

- Discovers cafes from OpenStreetMap in both metros.
- Finds direct Square, Toast, and SpotOn ordering pages.
- Records append-only price observations and changes in Supabase.
- Separates explicit drink sizes from inferred sizes.
- Publishes shop menus, drink comparisons, ratings when available, and a detailed OpenStreetMap view.
- Does not collect Uber Eats, DoorDash, or Grubhub prices.

## Collection

The `Collect coffee prices` GitHub Action runs at 00:30 UTC each day and can also run manually. It uses a service-side Supabase key. The public site receives only the publishable key and has read-only RLS access.

OpenStreetMap-derived locations are displayed with the required OpenStreetMap attribution.
