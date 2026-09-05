#!/usr/bin/env python3
"""Structured menu feeds behind the ordering platforms the collector labels.

The daily collector reads a shop's ordering page as HTML. That works for Square
Online, whose catalogue it fetches as JSON, and fails everywhere else: Toast and
ChowNow answer a Cloudflare challenge to any datacenter IP, and SpotOn,
Incentivio and Kyoo build their menus in the browser, so the DOM a runner gets
holds no priced rows at all. Those menus have arrived as staged captures under
imports/ ever since.

Every one of those platforms is also a public read API, and none of the ones
below needs a key, a token or a browser:

- **Toast** answers unauthenticated GraphQL at ws-api.toasttab.com over GET
  (POST is refused by the edge). `menusV3` returns the whole published menu for
  a restaurant guid, and `nearbyRestaurants` is a location directory, so a shop
  that never links Toast from its own website can still be matched to its menu.
- **SpotOn** server-renders the full catalogue into the `__NEXT_DATA__` blob of
  its ordering page.
- **Incentivio** serves a client alias -> locations -> catalogue chain from
  mobile.incentivio.com, priced in tenths of a cent.
- **Kyoo** publishes a Square-shaped catalogue JSON per location on S3.

ChowNow stays out: chownow.com answers 403 to every host and path from a
datacenter IP with a hard WAF block rather than a solvable challenge, so those
menus remain staged captures (see imports/README.md).

Extractors return collect.MenuItem lists, so the collector's own classifier,
size parser and write path handle them unchanged. Where a platform reports
priced option sets, they are normalised into the Square-shaped
``raw["modifiers"]["data"]`` that collect.extract_modifiers already reads.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import math
import re
import sys
import threading
import unicodedata
from typing import Any, Iterable
from urllib.parse import urlparse

from collect import METROS, MenuItem, get


def platform_of(url: str) -> str | None:
    """Ordering platform for a URL, including the ones collect.py cannot read.

    Mirrors collect.platform_of for the hosts they share so a caller can use
    either, and adds the API-only platforms on top.
    """
    host = urlparse(url).netloc.lower()
    if "toasttab.com" in host or "toast.app" in host:
        return "toast"
    if "order.spoton.com" in host:
        return "spoton"
    if "incentivio.com" in host:
        return "incentivio"
    if "kyoo.tech" in host or "cityflavor.com" in host:
        return "kyoo"
    return None


def cents(amount: Any, per_dollar: int = 1) -> int | None:
    """Money in a platform's own unit, as whole cents.

    ``per_dollar`` is how many of that unit make a dollar: Toast and SpotOn
    price in dollars (``4.75``, the default), Incentivio in tenths of a cent
    (``4750``), Square and Kyoo already in cents. bool is an int in Python, and
    a sold-out flag must never become a price.
    """
    if isinstance(amount, bool) or not isinstance(amount, (int, float, str)):
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return int(round(value * 100 / per_dollar))


def modifier_payload(groups: Iterable[tuple[str | None, list[tuple[str, int]]]]) -> dict[str, Any]:
    """Priced option sets in the shape collect.extract_modifiers reads.

    That reader was written against Square, which reports a choice's upcharge in
    dollars, so the deltas are converted back to dollars here rather than
    teaching every writer a second unit.
    """
    data = []
    for name, choices in groups:
        if not choices:
            continue
        data.append({"name": name, "choices": [{"name": choice, "price": delta / 100} for choice, delta in choices]})
    return {"modifiers": {"data": data}} if data else {}


def stable_id(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(part) for part in parts).lower().encode()).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Toast
TOAST_API = "https://ws-api.toasttab.com/do-federated-gateway/v1/graphql"
# A restaurant guid appears in a toast.app deep link as "r-<guid>" and in some
# embedded widgets on its own; a shortUrl only appears in an order.toasttab.com
# path. menusV3 keys on the guid, so a shortUrl has to go through the directory.
TOAST_GUID = re.compile(r"\br-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", re.I)
TOAST_BARE_GUID = re.compile(r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", re.I)
TOAST_SHORT_URL = re.compile(r"toasttab\.com/(?:online/)?([a-z0-9][a-z0-9-]{2,})", re.I)
# Paths that look like a shortUrl but are Toast's own pages, not a restaurant.
TOAST_NOT_SHORT = {"online", "local", "restaurants", "gift-cards", "giftcards", "checkout", "account"}
# nearbyRestaurants answers at most this many per call, so the metro sweep uses
# a grid fine enough that no single call can be truncated.
TOAST_PAGE_CAP = 299
TOAST_RADIUS_MILES = 3
TOAST_GRID_LAT = 0.05
TOAST_GRID_LNG = 0.06
# menusV3 answers with the online-ordering menu by default, which on most
# restaurants is a subset of what the counter sells: Alma publishes 99 items
# online and 651 on the register, and every price that appears in both is
# identical. Both are read and merged, so a shop's espresso list is priced even
# when only its lunch menu is orderable online.
TOAST_VISIBILITIES = (None, "POS")


def toast_query(query: str) -> dict[str, Any]:
    """One GraphQL read.

    The gateway refuses POST from outside its own origin but answers a GET with
    the query in the query string, which is the only shape used here.
    """
    payload = get(TOAST_API, params={"query": query}).json()
    for error in payload.get("errors") or []:
        print(f"Toast GraphQL: {error.get('message')}", file=sys.stderr)
    return payload.get("data") or {}


def toast_guid(url: str) -> str | None:
    match = TOAST_GUID.search(url) or TOAST_BARE_GUID.search(url)
    return match.group(1).lower() if match else None


def toast_short_url(url: str) -> str | None:
    match = TOAST_SHORT_URL.search(url)
    if not match:
        return None
    slug = match.group(1).lower().strip("-")
    return None if slug in TOAST_NOT_SHORT else slug


def toast_directory(metro: str) -> list[dict[str, Any]]:
    """Every Toast restaurant in a metro's bounding box.

    A shop that never links its ordering page - and the many with no website at
    all - can only be reached by matching the shop row against this directory.
    """
    south, west, north, east = METROS[metro]
    # Any time inside ordering hours returns the same list; noon UTC is a safe
    # constant that never lands on a day boundary in either metro.
    when = f"{dt.date.today().isoformat()}T12:00:00.000Z"
    found: dict[str, dict[str, Any]] = {}
    lats = [south + step * TOAST_GRID_LAT for step in range(int((north - south) / TOAST_GRID_LAT) + 2)]
    lngs = [west + step * TOAST_GRID_LNG for step in range(int((east - west) / TOAST_GRID_LNG) + 2)]
    for lat, lng in itertools.product(lats, lngs):
        query = (
            '{nearbyRestaurants(input:{diningOption:TAKE_OUT,fulfillmentDateTime:"%s",'
            "latitude:%.4f,longitude:%.4f,radius:%d}){guid name shortUrl "
            "location{address1 city state latitude longitude}}}" % (when, lat, lng, TOAST_RADIUS_MILES)
        )
        try:
            rows = toast_query(query).get("nearbyRestaurants") or []
        except Exception as exc:
            print(f"Toast directory {lat:.2f},{lng:.2f}: {exc}", file=sys.stderr)
            continue
        if len(rows) >= TOAST_PAGE_CAP:
            print(f"Toast directory truncated at {lat:.2f},{lng:.2f}", file=sys.stderr)
        for row in rows:
            found[row["guid"]] = row
    print(f"Toast directory: {len(found)} restaurants in {metro}")
    return list(found.values())


def toast_price(item: dict[str, Any]) -> tuple[int, int | None, int | None] | None:
    """(price, low, high) for a Toast item, in cents.

    An item the shop prices per size reports ``price: null`` and every size in
    ``prices``; the cheapest size is the comparable cup, the way Square's
    low/high subunits are read.
    """
    prices = [value for value in (cents(price) for price in item.get("prices") or []) if value]
    single = cents(item.get("price"))
    if single:
        return single, (min(prices) if prices else None), (max(prices) if prices else None)
    if prices:
        return min(prices), min(prices), max(prices)
    return None


def toast_rows(menus: list[dict[str, Any]], visibility: str | None) -> list[MenuItem]:
    """Menu rows out of one menusV3 response."""
    out = []
    for menu in menus:
        for group in menu.get("groups") or []:
            for item in group.get("items") or []:
                priced = toast_price(item)
                name = str(item.get("name") or "").strip()
                # An 86'd item keeps its published price and comes back
                # tomorrow, so outOfStock is recorded rather than filtered:
                # dropping it would mark the row removed every time the shop
                # runs out of oat milk.
                if not priced or not name:
                    continue
                price, low, high = priced
                # A menu group's own name is the section a shopper sees; the
                # menu above it ("Merchandise", "Cafe at Night") is coarser and
                # is kept on raw for provenance only.
                out.append(MenuItem(
                    item["guid"], name, (group.get("name") or "").strip() or None, price, low, high,
                    raw={"toast": {**item, "menu": menu.get("name"), "visibility": visibility or "ONLINE"}},
                ))
    return out


def extract_toast(guid: str) -> list[MenuItem]:
    """Every published item for one Toast restaurant guid.

    The gateway reports a Toast item's option sets as names only - the priced
    choices sit behind an ordering session - so Toast rows carry no modifiers.
    Their size prices do come through, in ``prices``.
    """
    out: dict[str, MenuItem] = {}
    for visibility in TOAST_VISIBILITIES:
        clause = f",visibility:{visibility}" if visibility else ""
        query = (
            '{menusV3(input:{restaurantGuid:"%s"%s}){... on MenusResponse{menus{name groups{name '
            "items{guid name description price prices outOfStock}}}}}}" % (guid, clause)
        )
        menus = (toast_query(query).get("menusV3") or {}).get("menus") or []
        for entry in toast_rows(menus, visibility):
            out[entry.platform_id] = entry
    return list(out.values())


# ---------------------------------------------------------------------------
# SpotOn
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def next_data(html: str) -> dict[str, Any]:
    match = NEXT_DATA.search(html)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except ValueError:
        return {}


def spoton_sections(page: dict[str, Any]) -> list[MenuItem]:
    """Menu rows out of a SpotOn ordering page's __NEXT_DATA__."""
    sections = ((page.get("props") or {}).get("pageProps") or {}).get("menuData") or []
    out: dict[str, MenuItem] = {}
    for section in sections:
        category = str(section.get("name") or "").strip() or None
        for item in section.get("menuItems") or []:
            price = cents(item.get("price"))
            name = str(item.get("name") or "").strip()
            if not price or not name:
                continue
            platform_id = str(item.get("id") or stable_id(name, category))
            # A SpotOn item can be listed under two sections; the first is the
            # one the shop leads with, so it names the row.
            out.setdefault(platform_id, MenuItem(
                platform_id, name, category, price,
                raw={"spoton": {k: v for k, v in item.items() if k != "modifiers"}},
            ))
    return list(out.values())


def extract_spoton(url: str) -> list[MenuItem]:
    """SpotOn's ordering page carries its whole catalogue server-rendered.

    Only the catalogue: a SpotOn item's option sets are fetched when a shopper
    opens the item, so these rows carry no modifiers.
    """
    return spoton_sections(next_data(get(url).text))


# ---------------------------------------------------------------------------
# Incentivio
INCENTIVIO_API = "https://mobile.incentivio.com/incentivio-mobile-api"
INCENTIVIO_SLUG = re.compile(r"incentivio\.com/c/([A-Za-z0-9_-]+)", re.I)
# Prices arrive in tenths of a cent: 4750 is $4.75.
INCENTIVIO_UNIT = 1000
# A menu can grow past a single page of locations; the web app asks for
# everything at once with a radius that spans the planet.
INCENTIVIO_LOCATIONS = {
    "count": 10000, "latitude": 0, "longitude": 0, "page": 0, "radius": 11029160,
    "sortby": "title", "sortdirection": "DESC", "langCode": "en",
    "iscatering": "false", "markdeliverablelocations": "false", "ismenubrowsing": "false",
}


# A word for casing purposes, apostrophes included so "ARNIE'S" does not become
# "Arnie'S", and never starting mid-token so "16OZ" does not become "16Oz".
SHOUTED_WORD = re.compile("(?<![A-Za-z0-9'\u2019])[A-Za-z][A-Za-z'\u2019]*")


def incentivio_slug(url: str) -> str | None:
    match = INCENTIVIO_SLUG.search(url)
    return match.group(1) if match else None


def incentivio_headers(client_id: str | None = None) -> dict[str, str]:
    headers = {"Accept": "application/json", "inc-device": "WEB", "inc-user-language": "EN"}
    if client_id:
        headers["CLIENTID"] = client_id
    return headers


def incentivio_client(slug: str) -> str:
    return get(f"{INCENTIVIO_API}/clientalias/{slug}", headers=incentivio_headers()).json()["clientId"]


def pick_location(shop: dict[str, Any] | None, locations: list[dict[str, Any]],
                  coords: Any, address: Any) -> dict[str, Any] | None:
    """The branch of a multi-location merchant that this shop row is.

    A chain's cafes usually share a menu but not always a price list, and a shop
    row is one address, so without this every Anodyne cafe would be priced from
    whichever location the platform happened to list first. Coordinates decide
    it where the platform publishes them and the street number where it does
    not; when neither side says, the first location stands.
    """
    if not locations:
        return None
    lat, lng = (shop or {}).get("lat"), (shop or {}).get("lng")
    wanted = house_number((shop or {}).get("address"))
    best: tuple[float, dict[str, Any]] | None = None
    for location in locations:
        point = coords(location)
        if point and lat is not None and lng is not None:
            metres = metres_between(float(lat), float(lng), point[0], point[1])
        elif wanted and house_number(address(location)) == wanted:
            metres = 0.0
        else:
            continue
        if best is None or metres < best[0]:
            best = (metres, location)
    return best[1] if best else locations[0]


def incentivio_locations(client_id: str) -> list[dict[str, Any]]:
    payload = get(f"{INCENTIVIO_API}/locations", params=INCENTIVIO_LOCATIONS, headers=incentivio_headers(client_id)).json()
    return payload.get("stores") or []


def incentivio_title(node: dict[str, Any]) -> str:
    """The display title, which is localised, rather than the internal one.

    An item's own ``title`` is prefixed with its store ("Bay View - AMERICANO");
    the English displayInfo entry carries the name a shopper reads. Incentivio
    stores names in capitals and the app cases them for display, so a name with
    no lower case at all is cased here rather than shouted across the site.
    """
    title = ""
    for info in node.get("displayInfo") or []:
        if str(info.get("langCode") or "").upper() in ("EN", "") and info.get("title"):
            title = str(info["title"]).strip()
            break
    title = title or str(node.get("title") or "").strip()
    if not title or title != title.upper() or not any(char.isalpha() for char in title):
        return title
    # str.title() would write "Arnie'S Day Off" and "16Oz"; only a letter that
    # starts a word gets capitalised.
    return SHOUTED_WORD.sub(lambda match: match.group(0).capitalize(), title.lower())


def incentivio_options(item: dict[str, Any]) -> tuple[list[tuple[str, int]], dict[str, Any]]:
    """(size choices, modifier payload) for one Incentivio item.

    Most drinks are priced ``dynamic``: the item itself costs nothing and the
    real price sits on a single-select size group. Those become one row per
    size, the way the shop prices them; every other priced group is a modifier.
    """
    sizes: list[tuple[str, int]] = []
    groups: list[tuple[str | None, list[tuple[str, int]]]] = []
    for group in item.get("optionGroups") or []:
        name = incentivio_title(group)
        choices = []
        for option in group.get("items") or []:
            label = incentivio_title(option)
            delta = cents(option.get("price") or 0, INCENTIVIO_UNIT) or 0
            if label:
                choices.append((label, delta))
        if not choices:
            continue
        single = group.get("minItemSelections") == 1 and group.get("maxItemSelections") == 1
        if single and not sizes and any(delta for _, delta in choices):
            sizes = choices
        else:
            groups.append((name, choices))
    return sizes, modifier_payload(groups)


def extract_incentivio(slug: str, store_id: str | None = None,
                       shop: dict[str, Any] | None = None) -> list[MenuItem]:
    """One Incentivio store's catalogue, as one row per priced size."""
    client_id = incentivio_client(slug)
    if store_id is None:
        store = pick_location(shop, incentivio_locations(client_id),
                              lambda row: (row.get("latitude"), row.get("longitude")) if row.get("latitude") else None,
                              lambda row: (row.get("address") or {}).get("streetAddress1"))
        if not store:
            return []
        store_id = store["storeId"]
    params = {
        "checksum": "1", "clientId": client_id, "includeChildElements": "true",
        "localDate": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "storeId": store_id, "langCode": "en",
    }
    catalogs = get(f"{INCENTIVIO_API}/cachedcatalogs/compressed", params=params, headers=incentivio_headers(client_id)).json()
    out: dict[str, MenuItem] = {}
    for catalog in catalogs:
        for group in catalog.get("groups") or []:
            category = incentivio_title(group) or incentivio_title(catalog) or None
            for item in group.get("items") or []:
                name = incentivio_title(item)
                if not name:
                    continue
                sizes, modifiers = incentivio_options(item)
                base = cents(item.get("price") or 0, INCENTIVIO_UNIT)
                raw = {"incentivio": {"itemId": item.get("itemId"), "group": category, "storeId": store_id}, **modifiers}
                priced = [(f"{name} ({label})", price, f"{item.get('itemId')}:{label}")
                          for label, price in sizes if price] if not base else []
                for full, price, key in priced or ([(name, base, str(item.get("itemId")))] if base else []):
                    out[key] = MenuItem(key, full, category, price, raw=raw)
    return list(out.values())


# ---------------------------------------------------------------------------
# Kyoo
KYOO_API = "https://o.cityflavor.com"
KYOO_CATALOG = "https://kyoo-catalog.s3.amazonaws.com/catalog"
KYOO_MERCHANT = re.compile(r"merchants/([A-Z0-9]{8,})", re.I)


def kyoo_merchant(url: str) -> str | None:
    match = KYOO_MERCHANT.search(url)
    return match.group(1).upper() if match else None


def kyoo_locations(merchant_id: str) -> list[dict[str, Any]]:
    payload = get(f"{KYOO_API}/merchants/{merchant_id}", headers={"Accept": "application/json"}).json()
    return payload.get("kyoo_locations") or []


def kyoo_modifiers(variation: dict[str, Any]) -> dict[str, Any]:
    parsed = []
    for group in variation.get("modifier_lists") or []:
        choices = []
        for option in group.get("modifiers") or []:
            name = option.get("name")
            delta = (option.get("price_money") or {}).get("amount") or 0
            if isinstance(name, str) and name.strip():
                choices.append((name.strip(), int(delta)))
        parsed.append((group.get("name"), choices))
    return modifier_payload(parsed)


def kyoo_items(node: dict[str, Any], category: str | None) -> Iterable[MenuItem]:
    """Kyoo publishes a Square catalogue: nested categories of items of variations."""
    label = str(node.get("name") or "").strip() or category
    for child in node.get("subcategories") or []:
        yield from kyoo_items(child, label)
    for item in node.get("items") or []:
        name = str(item.get("name") or "").strip()
        variations = item.get("variations") or []
        for variation in variations:
            price = (variation.get("price_money") or {}).get("amount")
            if not isinstance(price, int) or price <= 0 or not name:
                continue
            size = str(variation.get("name") or "").strip()
            # A lone "Regular" variation is the item itself, not a size.
            full = f"{name} ({size})" if size and len(variations) > 1 else name
            raw = {"kyoo": {"item_id": item.get("id"), "variation_id": variation.get("id")}, **kyoo_modifiers(variation)}
            yield MenuItem(str(variation.get("id") or stable_id(full)), full, label, price, raw=raw)


def extract_kyoo(merchant_id: str, location_id: str | None = None,
                 shop: dict[str, Any] | None = None) -> list[MenuItem]:
    if location_id is None:
        # Kyoo publishes an address per location and no coordinates, so the
        # street number is all there is to tell one Stone Creek cafe from nine.
        location = pick_location(shop, kyoo_locations(merchant_id), lambda row: None,
                                 lambda row: (row.get("kyoo_address") or {}).get("address_line1"))
        if not location:
            return []
        location_id = location["location_id"]
    url = f"{KYOO_CATALOG}/merchants/{merchant_id}/locations/{location_id}/all-catalog.json"
    catalog = get(url, headers={"Accept": "application/json"}).json()
    out: dict[str, MenuItem] = {}
    for category in catalog:
        for entry in kyoo_items(category, None):
            out[entry.platform_id] = entry
    return list(out.values())


# ---------------------------------------------------------------------------
# Matching a shop row to a platform's own directory.
#
# Two thirds of the shops in these metros never link their ordering page, and a
# third have no website at all, so the only way to price them is to look them up
# in the platform's directory. A wrong match prices a coffee shop from a steak
# house's menu, so a candidate has to agree on BOTH where it is and what it is
# called: within GEO_METRES of the shop's coordinates, and either the same name
# or the same distinctive words once the words every cafe shares are removed.
GEO_METRES = 250
GEO_EXACT_METRES = 500
NAME_OVERLAP = 0.6
# Words that say "this is a cafe" rather than which cafe, plus the filler that
# separates a shop from its own branch name.
GENERIC_WORDS = {
    "the", "a", "and", "cafe", "caf", "coffee", "coffeehouse", "coffeeshop", "house",
    "company", "co", "roasters", "roasting", "roastery", "bakery", "bakeshop", "shop",
    "bar", "kitchen", "restaurant", "llc", "inc", "of", "at", "on", "eatery", "market",
}


def name_words(name: str) -> list[str]:
    """A name as comparable words, with accents folded and articles dropped.

    "Dia Cafe" and "Dia Cafe" have to compare equal, so the accents come off
    before the non-letters do; otherwise a stray e-acute splits a word in two.
    """
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    words = [word for word in re.sub(r"[^a-z0-9]+", " ", folded.lower()).split() if word]
    return words[1:] if len(words) > 1 and words[0] == "the" else words


def core_words(name: str) -> set[str]:
    words = name_words(name)
    core = {word for word in words if word not in GENERIC_WORDS and not word.isdigit()}
    # "The Coffee House" is all filler; fall back to the whole name rather than
    # matching everything in the metro.
    return core or set(words)


HOUSE_NUMBER = re.compile(r"^\s*(\d{1,6})\b")


def house_number(address: str | None) -> str | None:
    match = HOUSE_NUMBER.match(address or "")
    return match.group(1) if match else None


def metres_between(lat: float, lng: float, other_lat: float, other_lng: float) -> float:
    return math.hypot((lat - other_lat) * 111_320, (lng - other_lng) * 111_320 * math.cos(math.radians(lat)))


def same_place(shop_name: str, listing_name: str, metres: float,
               shop_address: str | None = None, listing_address: str | None = None) -> bool:
    """Whether a directory listing is this shop, given how far away it sits.

    Two cafes can share a block and half a name: Highland Cafe and Bakery sits
    a few doors from Highland Grill. Where both sides state a street number, a
    different number settles it before any name rule runs.
    """
    numbers = (house_number(shop_address), house_number(listing_address))
    if all(numbers) and numbers[0] != numbers[1]:
        return False
    shop_words, listing_words = name_words(shop_name), name_words(listing_name)
    if not shop_words or not listing_words:
        return False
    # A branch suffix is normal ("Haven" vs "Haven Cafe 1201 N Van Buren"), so a
    # name that is the whole shop name plus a suffix is the same place, and is
    # trusted a little further out because a shop's OSM node can sit across the
    # street from the address the platform holds.
    if shop_words == listing_words or listing_words[: len(shop_words)] == shop_words or shop_words[: len(listing_words)] == listing_words:
        return metres <= GEO_EXACT_METRES
    if metres > GEO_METRES:
        return False
    shop_core, listing_core = core_words(shop_name), core_words(listing_name)
    shared = shop_core & listing_core
    # One distinctive word in common is the floor. Without the length guard a
    # shared "mos" would marry Mo's Irish Pub to Mo's A Place for Steaks.
    if not any(len(word) >= 4 for word in shared):
        return False
    # A platform listing routinely adds the branch to the name a shop goes by
    # ("Haraz Coffee House" is listed as "Haraz Coffee - Milwaukee"), so one
    # name's distinctive words being a subset of the other's is a match; short
    # of that, the two have to be mostly the same words.
    if shared in (shop_core, listing_core):
        return True
    return len(shared) / len(shop_core | listing_core) >= NAME_OVERLAP


_DIRECTORIES: dict[str, list[dict[str, Any]]] = {}
# The collector resolves shops from a thread pool, and a directory sweep is a
# hundred requests, so the first thread to ask builds it and the rest wait.
_DIRECTORY_LOCK = threading.Lock()


def directory(metro: str) -> list[dict[str, Any]]:
    """The metro's Toast directory, built once per process."""
    with _DIRECTORY_LOCK:
        if metro not in _DIRECTORIES:
            try:
                _DIRECTORIES[metro] = toast_directory(metro)
            except Exception as exc:
                print(f"Toast directory failed for {metro}: {exc}", file=sys.stderr)
                _DIRECTORIES[metro] = []
        return _DIRECTORIES[metro]


def directory_source(shop: dict[str, Any]) -> tuple[str, str] | None:
    """(platform, source) for a shop found in a platform directory, else None.

    The source is the shop's own ordering URL rather than the bare guid, so the
    observation rows point at a page a reader can open.
    """
    metro, lat, lng = shop.get("metro"), shop.get("lat"), shop.get("lng")
    if metro not in METROS or lat is None or lng is None:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for listing in directory(metro):
        location = listing.get("location") or {}
        if location.get("latitude") is None or location.get("longitude") is None:
            continue
        metres = metres_between(float(lat), float(lng), location["latitude"], location["longitude"])
        if not same_place(shop.get("name") or "", listing.get("name") or "", metres,
                          shop.get("address"), location.get("address1")):
            continue
        if best is None or metres < best[0]:
            best = (metres, listing)
    if best is None:
        return None
    listing = best[1]
    return "toast", f"https://order.toasttab.com/online/{listing['shortUrl']}?guid={listing['guid']}"


# ---------------------------------------------------------------------------
def toast_guid_for(source: str) -> str | None:
    """The restaurant guid a Toast link points at.

    A toast.app deep link carries the guid; an order.toasttab.com link carries
    only the shortUrl, and menusV3 keys on the guid, so the directory is what
    turns one into the other.
    """
    guid = toast_guid(source)
    if guid:
        return guid
    slug = toast_short_url(source)
    if not slug:
        return None
    for metro in METROS:
        for listing in directory(metro):
            if (listing.get("shortUrl") or "").lower() == slug:
                return listing["guid"]
    return None


EXTRACTORS = {
    "toast": lambda source, location, shop: extract_toast(toast_guid_for(source) or source),
    "spoton": lambda source, location, shop: extract_spoton(source),
    "incentivio": lambda source, location, shop: extract_incentivio(incentivio_slug(source) or source, location, shop),
    "kyoo": lambda source, location, shop: extract_kyoo(kyoo_merchant(source) or source, location, shop),
}


def extract(platform: str, source: str, location: str | None = None,
            shop: dict[str, Any] | None = None) -> list[MenuItem]:
    """Menu rows for one shop on one platform, or [] when the platform is not ours.

    ``location`` names a branch outright; ``shop`` lets a merchant with several
    of them be resolved from the shop row's own address.
    """
    extractor = EXTRACTORS.get(platform)
    return extractor(source, location, shop) if extractor else []
