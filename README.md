# Coffee Prices

A coffee price website for Milwaukee and the Twin Cities. Look up what shops charge, compare a drink across shops, and browse the map.

Live at https://tylerherman19.github.io/Coffee/

The index loads a saved public snapshot while fresh database requests run. A failed ratings request does not hide menus. Every published build refreshes that snapshot; successful collector runs trigger a new Pages build. Menu rows keep their own last-checked dates, and comparisons exclude prices older than 60 days by default. Size filters use explicitly stated ounces only.

The daily collector discovers shops in OpenStreetMap, then reads known direct menu sources. An Overpass outage falls back to existing shop rows, records a warning, and continues menu collection. Menu writes reuse database connections and batch unchanged-item refreshes. Failed or empty reads preserve previously collected prices. All data-writing workflows share a concurrency group to avoid conflicting updates.

Verified additions live in `data/verified_shops.json`. Blue Hour Coffee's location and hours come from its official website; its HTML menu is collected directly from https://bluehourcoffee.com/menu. The verified-menu workflow syncs those shops, scrapes their current menus, and corrects existing drink classifications when collector changes reach main.

Validation:

```sh
npm ci
npm run lint
npx tsc --noEmit
node --experimental-strip-types --test scripts/test_site.mjs
pip install -r requirements.txt
python scripts/test_classify.py
python scripts/test_menu_sources.py
python scripts/test_collector.py
```

Some menus are unavailable to automation or are captured manually. Missing prices remain unavailable; they are never estimated from another shop. A listed price is the last published-menu observation, before tax and add-ons, rather than a guarantee of today's counter price.
