#!/usr/bin/env python3
"""Collect public, direct-order coffee shop menus without delivery marketplaces."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "CoffeePrices/1.0 (+https://github.com/tylerherman19/Coffee; public-menu research)"
TIMEOUT = 18
OVERPASS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
METROS = {
    "milwaukee": (42.92, -88.07, 43.20, -87.86),
    # (south, west, north, east). West edge reaches -93.65 to cover the western
    # metro: Plymouth, Wayzata, Minnetonka and the Lake Minnetonka towns.
    "twin_cities": (44.85, -93.65, 45.10, -92.98),
}
DIRECT_HOSTS = ("square.site", "squareup.com", "square.link", "toast.app", "toasttab.com", "order.spoton.com", "chownow.com")
# Delivery marketplaces, whose prices are marked up over the shop's own menu.
# ChowNow is not one of them: it is white-label ordering that bills the shop,
# not a marketplace with its own fleet and its own prices, so it belongs in
# DIRECT_HOSTS above. It is served through a Cloudflare bot challenge that
# answers 403 to every host and API path from a datacenter IP, so the runner
# cannot read those menus - they arrive as staged captures under imports/
# instead (see imports/README.md). Discovering the link still matters: it
# labels the shop's ordering platform and stops the daily run from wiping
# that label off the four shops whose menus were captured by hand.
BLOCKED_HOSTS = ("ubereats.com", "doordash.com", "order.online", "grubhub.com", "clover.com")


@dataclass
class MenuItem:
    platform_id: str
    name: str
    category: str | None
    price_cents: int
    low_cents: int | None = None
    high_cents: int | None = None
    raw: dict[str, Any] | None = None


class Supabase:
    def __init__(self) -> None:
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SECRET_KEY"]
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Accept-Profile": "coffee",
            "Content-Profile": "coffee",
            "Content-Type": "application/json",
        }

    def get(self, table: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        response = requests.get(f"{self.url}/rest/v1/{table}", params=params, headers=self.headers, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()

    def post(self, table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        headers = {**self.headers, "Prefer": "return=representation"}
        response = requests.post(f"{self.url}/rest/v1/{table}", headers=headers, json=rows, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()

    def patch(self, table: str, query: str, values: dict[str, Any]) -> None:
        headers = {**self.headers, "Prefer": "return=minimal"}
        response = requests.patch(f"{self.url}/rest/v1/{table}?{query}", headers=headers, json=values, timeout=TIMEOUT)
        response.raise_for_status()


def get(url: str, **kwargs: Any) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"}
    headers.update(kwargs.pop("headers", {}))
    response = requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True, **kwargs)
    response.raise_for_status()
    return response


def discover(metro: str) -> list[dict[str, Any]]:
    south, west, north, east = METROS[metro]
    query = f'''[out:json][timeout:45];(
      nwr["amenity"="cafe"]({south},{west},{north},{east});
      nwr["shop"="coffee"]({south},{west},{north},{east});
      nwr["cuisine"="coffee_shop"]({south},{west},{north},{east});
    );out center tags;'''
    payload = None
    for endpoint in OVERPASS:
        try:
            payload = get(endpoint, params={"data": query}).json()
            break
        except Exception as exc:
            print(f"Overpass mirror failed: {endpoint}: {exc}", file=sys.stderr)
            time.sleep(2)
    if payload is None:
        raise RuntimeError(f"All Overpass mirrors failed for {metro}")
    shops: dict[str, dict[str, Any]] = {}
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lng = element.get("lon") or element.get("center", {}).get("lon")
        if lat is None or lng is None:
            continue
        osm_id = f"{element.get('type','n')[0]}{element['id']}"
        street = " ".join(part for part in [tags.get("addr:housenumber"), tags.get("addr:street")] if part)
        locality = tags.get("addr:city") or ("Milwaukee" if metro == "milwaukee" else "Minneapolis–Saint Paul")
        address = ", ".join(part for part in [street, locality, tags.get("addr:state")] if part) or None
        website = tags.get("website") or tags.get("contact:website") or tags.get("url")
        shops[osm_id] = {
            "name": name.strip(), "metro": metro, "address": address,
            "neighborhood": tags.get("addr:neighbourhood") or tags.get("addr:suburb"),
            "lat": lat, "lng": lng, "website": website, "osm_id": osm_id,
            "is_chain": bool(tags.get("brand")), "brand": tags.get("brand"),
            "opening_hours": tags.get("opening_hours"), "data_source": "openstreetmap",
            "last_seen": dt.date.today().isoformat(),
        }
    print(f"Discovered {len(shops)} shops in {metro}")
    return list(shops.values())


def normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


# A gift-card or loyalty page sits on the same host as the menu and often
# appears first in the markup, so the old "first matching link wins" picked it
# and every one of those shops collected nothing.
NON_MENU_PATHS = re.compile(r"egiftcard|giftcard|gift-card|/gift/|/gift$|rewardssignup|/loyalty|/donate|/careers|/rewards", re.I)
# Link text or href that suggests the ordering page, used to crawl one level in.
ORDER_HINT = re.compile(r"\border\b|\bmenu\b|shop online|order online|buy|store", re.I)


def platform_of(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    if any(blocked in host for blocked in BLOCKED_HOSTS):
        return None
    if "square.site" in host or "squareup.com" in host or "square.link" in host:
        return "square"
    if "toast.app" in host or "toasttab.com" in host:
        return "toast"
    if "order.spoton.com" in host:
        return "spoton"
    if "chownow.com" in host:
        return "chownow"
    return None


def rank_candidate(url: str) -> int:
    """Lower sorts first. Prefers a real ordering path over a bare host."""
    path = urlparse(url).path.strip("/")
    if NON_MENU_PATHS.search(url):
        return 90
    if not path:
        return 50  # bare "toast.app/" style link, usually a powered-by badge
    if "/s/order" in url or re.search(r"\border\b", path, re.I):
        return 0
    if re.search(r"\bmenu\b", path, re.I):
        return 10
    return 20


# Shops embed the ordering link in an iframe, a button's JS handler or a JSON
# blob at least as often as in an <a href>, so the anchor scan alone missed
# most of them. This finds a platform URL anywhere in the markup.
EMBEDDED_URL = re.compile(
    r"https?://[A-Za-z0-9._~%-]*(?:square\.site|squareup\.com|square\.link|toasttab\.com|toast\.app|order\.spoton\.com|chownow\.com)[A-Za-z0-9._~%!$&'()*+,;=:@/?#-]*",
    re.I,
)


def platform_links(html: str, base: str) -> list[str]:
    found: list[str] = []
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = urljoin(base, anchor.get("href"))
        if any(host in href.lower() for host in DIRECT_HOSTS):
            found.append(href)
    for match in EMBEDDED_URL.finditer(html):
        found.append(match.group(0).rstrip("\\\"'),;."))
    return found


def direct_link(home_url: str) -> tuple[str | None, str | None, str | None]:
    try:
        response = get(home_url)
    except Exception:
        return None, None, None
    candidates = [response.url, *platform_links(response.text, response.url)]
    # Many shops link the ordering platform from an Order/Menu page rather than
    # the homepage, which the old single-page scan could never reach.
    if not any(platform_of(url) for url in candidates):
        soup = BeautifulSoup(response.text, "html.parser")
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(response.url, anchor.get("href"))
            if urlparse(href).netloc != urlparse(response.url).netloc:
                continue
            if not ORDER_HINT.search(f"{anchor.get_text(' ', strip=True)} {href}"):
                continue
            if href in seen or len(seen) >= 4:
                continue
            seen.add(href)
            try:
                inner = get(href)
            except Exception:
                continue
            candidates.extend([inner.url, *platform_links(inner.text, inner.url)])
    best = sorted((url for url in candidates if platform_of(url) and not NON_MENU_PATHS.search(url)), key=rank_candidate)
    for candidate in best:
        platform = platform_of(candidate)
        if platform:
            cached = response.text if candidate == response.url else None
            return platform, candidate, cached
    return None, None, None


# Packaging beats every drink word: "Espresso Whole Bean" and "5 Gallon Hot
# Coffee" are a retail bag and a catering urn, not a cup anyone can compare.
RETAIL_PACKAGING = re.compile(
    r"whole bean|\bbeans\b|\bground\b|\bbags?\b|\blbs?\b|\bpounds?\b|pre.?pack|"
    r"k.?cups?\b|\bgallons?\b|\bbox\b|traveler|\bscoop\b|liqueur|subscription|"
    r"gift ?card|\bmerch\b|\bmugs?\b|tumbler|\bfilters?\b|\bcanteen\b|"
    r"\bjoe to go\b|for the crew|\binstant\b|\bspreads?\b|\bcarafes?\b|"
    r"\bgrinders?\b|\btotes?\b|pup ?cups?\b|\bplatters?\b|\btrays?\b|\bpcs?\b|"
    r"\bcartons?\b|\bairpots?\b|\bcambros?\b|\bgrowlers?\b|\btins?\b|\bcleanse\b|"
    r"\bblends?\b|ball cap|bandanas?|joe\s?2\s?go|\s//\s|\bcatering\b|\bglassware\b|"
    # A flight or tasting is several small pours at one price, so it is not
    # comparable to a cup and would top the drip ranking at a flight's price.
    r"\bflights?\b|\bsamplers?\b|\btastings?\b",
    re.I,
)
# A leading ounce size is a retail bag's naming style ("10Oz Decaf",
# "96oz Coffee for the Crew") - drinks lead with the drink name.
RETAIL_LEADING_SIZE = re.compile(r"^\d{1,3}\s?(?:fl\.?\s*)?oz\b", re.I)
# Merch named after the drink it serves ("Vero Cappuccino Glass"). Matched on
# the item name only, and only at the end, so "Glass of Milk" stays a drink.
MERCH_TAIL = re.compile(r"\bglass(?:es)?\s*$", re.I)

# Bakery words, by contrast, double as drink flavours ("Cheese Cake Cold Brew",
# "Cinnamon Roll Latte"), so they disqualify an item only when the bakery word
# comes after the drink word in the name (see classify_name).
FOOD_ITEM = re.compile(
    r"\bcakes?\b|\brolls?\b|\bmuffins?\b|\bcookies?\b|\bscones?\b|croissant|"
    r"\bbagels?\b|\bdo(?:ugh)?nuts?\b|brownie|\bpastr|sandwich|\btoast\b|"
    r"\bbars?\b|\bpies?\b|\bloaf\b|biscuit|danish|quiche|burrito|\bwraps?\b|"
    r"\byogurts?\b(?! ?drinks?\b)|\bparfaits?\b|\bgranola\b",
    re.I,
)
# Blended drinks are drinks, but a shake is not a latte and a frappe is not
# drip; keeping them out of the named buckets keeps the compare view honest.
BLENDED = re.compile(r"\bshakes?\b|frapp|smoothie|\bmalt\b|\bslush", re.I)
# The same reasoning, one step later: a frozen/blended "cooler" and an espresso
# martini are real drinks with a real price, but they are not the cup the
# compare view is ranking, so they land in "other" rather than a named bucket.
# Unlike BLENDED these never promote a non-drink - "Freshly Frozen Dinner
# Rolls" stays a bakery item.
NOT_A_CUP = re.compile(
    r"\bfrozen\b|\bblended\b|\bcoolers?\b|\bchillers?\b|\bblenders?\b|"
    r"\bbeers?\b|\bwines?\b|\w*tini\b|\bcocktails?\b|\bmimosas?\b|prosecco|"
    r"champagne|\bwhisk(?:e)?y\b|\bvodka\b|\btequila\b|\bnegroni\b|\bsangria\b|"
    r"\bipa\b|\blagers?\b|\bstouts?\b|\bpilsner\b|\bboozy\b|\bspiked\b",
    re.I,
)
# An upcharge is not a cup: "Extra Shot Espresso" at $0.75 would otherwise be
# the cheapest espresso in the metro. Anchored to the front of the name (or a
# parenthetical) so a real drink named "Espresso Shot" survives.
ADD_ON = re.compile(
    r"^(?:extra|add|additional|side of|sub|substitute|upcharge)\b|"
    r"^shot of\b|\(add\b|\badd[- ]?ons?\b|\bflavor shot\b|\bextra\s*$",
    re.I,
)
DRINK_KINDS = [
    # Caramel latte is its own bucket and must beat the generic "latte"
    # and "mocha" rules, which the same names also match.
    ("caramel_latte", r"(?:caramel|carmel)\W+(?:\w+\W+){0,3}?latte|"
                      r"latte\W+(?:\w+\W+){0,3}?(?:caramel|carmel)"),
    ("cold_brew", r"cold brew|nitro"),
    ("cappuccino", r"cappuccino"),
    ("americano", r"americano"),
    ("espresso", r"espresso|cortado|\bristretto\b|\bdoppio\b"),
    ("mocha", r"mocha"),
    ("latte", r"latte|cafe au lait|café au lait"),
    # A bare "Coffee", "Hot Coffee" or "Coffee of the Day" is the drip cup on
    # most menus. This rule is broad, so it is the one the bakery guard covers.
    ("drip", r"drip|pour.?over|brewed coffee|batch brew|\bcoffee\b"),
    ("chai", r"chai"),
    ("tea", r"\btea\b|matcha"),
]
BROAD_KINDS = {"drip"}


# Food/retail categories are never drinks, whatever the item name contains
# (e.g. "Vanilla Mocha Cake" in Bakery is not a mocha).
NON_DRINK_CATEGORY = re.compile(
    r"\b(bakery|pastry|pastries|food|breakfast|sandwich|sandwiches|salad|salads|"
    r"cake|cakes|dessert|desserts|pizza|soup|wrap|wraps|kitchen|retail|beans|merch|merchandise|"
    r"catering|platters?|trays?|supplies|gifts?|kits|snacks|for the group)\b",
    re.I,
)
# A "Non-Coffee" section header contains the word "coffee", so letting it name
# a kind turned every Italian soda under it into drip.
NEGATED_CATEGORY = re.compile(r"non[- ]?coffee|no coffee|not coffee|caffeine[- ]?free", re.I)
GENERIC_DRINK = re.compile(
    r"\b(coffees?|drinks?|beverages?|iced|lemonades?|smoothies?|juices?|"
    r"refreshers?|frappes?|sodas?|cocoa|coco|cider|hot chocolate)\b",
    re.I,
)


def classify_name(name: str, category: str | None = None) -> tuple[bool, str | None]:
    """(is a comparable drink, drink kind) for one menu item.

    The item's own NAME decides the kind; the category is only consulted when
    the name names nothing. Reading both as one string made a section header
    outvote the item: Colectivo's "Latte" and "Mocha" sit under an "Espresso"
    heading and were filed as espresso, Stone Creek's "Mulled Citrus Chai"
    under "Tea/Chai & Tea Lattes" was filed as a latte, and every drink in
    UP Cafe's "Up Coffee - Drinks" was filed as drip.
    """
    lowered = name.lower()
    text = f"{name} {category or ''}".lower()
    if category and NON_DRINK_CATEGORY.search(category):
        return False, None
    if RETAIL_PACKAGING.search(text) or RETAIL_LEADING_SIZE.search(lowered) or MERCH_TAIL.search(name):
        return False, None
    if ADD_ON.search(name):
        return False, None
    if BLENDED.search(text):
        return True, "other"
    # Macchiato is checked on the NAME alone so a "Caramel Macchiato" is a
    # macchiato (espresso bucket) rather than a caramel latte, without letting
    # an "Espresso" category outvote the item's own name in the kind loop.
    if re.search(r"\bmacchiato\b", name, re.I):
        return True, "espresso"
    food = FOOD_ITEM.search(lowered)
    for kind, pattern in DRINK_KINDS:
        match = re.search(pattern, lowered)
        if not match:
            continue
        # A flavour puts the bakery word before the drink word ("Carrot Cake
        # Latte"); a pastry puts it after ("Mocha Chip Rawr Bar").
        if food and food.start() > match.start():
            return False, None
        if kind in BROAD_KINDS and food:
            return False, None
        return True, "other" if NOT_A_CUP.search(text) else kind
    # Nothing in the name: let the section header name the kind instead.
    if category and not NEGATED_CATEGORY.search(category):
        lowered_category = category.lower()
        for kind, pattern in DRINK_KINDS:
            if not re.search(pattern, lowered_category):
                continue
            if food:
                # "Pecan Pie" under "Espresso Shots" is a pastry; "Frozen
                # Cookies & Cream" under "Tea, Cocoa & More" is a blended drink.
                return (True, "other") if NOT_A_CUP.search(text) else (False, None)
            return True, "other" if NOT_A_CUP.search(text) else kind
    # Nothing named a kind, so a bakery word anywhere - the name or a "Cookies"
    # section header - is the strongest signal left.
    if food or FOOD_ITEM.search(text):
        return False, None
    is_drink = bool(GENERIC_DRINK.search(text))
    return is_drink, "other" if is_drink else None


# Prices and serving sizes reach the row after classify_name has run, and they
# settle cases the name alone cannot: a $0.75 "drink" is a syrup pump, a $35
# one is a catering box, a 64 oz one is a group vessel. Every writer
# (collector, staged import, remediation sweep) goes through here so a fresh
# collection cannot re-introduce rows a past sweep already removed.
RETAIL_PRICE_GUARD = re.compile(r"retail|supplies|theory|guest coffee", re.I)
GROUP_VESSEL_OZ = 32
ADD_ON_CENTS = 100
NOT_A_CUP_CENTS = 2000
RETAIL_CENTS = 1000


def refine_classification(
    name: str,
    category: str | None,
    price_cents: int | None,
    size_oz: float | None,
) -> tuple[bool, str | None]:
    is_drink, drink_type = classify_name(name, category)
    if not is_drink:
        return is_drink, drink_type
    if size_oz is not None and size_oz >= GROUP_VESSEL_OZ:
        return False, None
    if price_cents is None:
        return is_drink, drink_type
    if price_cents < ADD_ON_CENTS or price_cents >= NOT_A_CUP_CENTS:
        return False, None
    if price_cents >= RETAIL_CENTS:
        if category and RETAIL_PRICE_GUARD.search(category):
            return False, None
        # "$18 ... 12 oz" is a retail bean bag's naming style.
        if re.search(r"\d{1,3}\s?oz\b", name, re.I):
            return False, None
    return is_drink, drink_type


def parse_size(name: str) -> tuple[str | None, float | None, str]:
    match = re.search(r"\b(\d{1,2}(?:\.\d)?)\s*(?:fl\.?\s*)?oz\b", name, re.I)
    if match:
        return match.group(0), float(match.group(1)), "explicit"
    for label, ounces in (("small", 8), ("regular", 12), ("medium", 12), ("large", 16)):
        if re.search(rf"\b{label}\b", name, re.I):
            return label.title(), float(ounces), "inferred"
    return None, None, "none"


def extract_square(url: str, cached_html: str | None = None) -> list[MenuItem]:
    # The discovered link can point anywhere on the store ("/delivery",
    # "/menu"), and the ordering page always lives at the site root, so build
    # it from the origin rather than appending to whatever path we landed on.
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    response = None
    for order_url in ([url] if "/s/order" in url else []) + [f"{origin}/s/order", origin]:
        try:
            response = get(order_url)
            break
        except Exception:
            continue
    if response is None:
        return []
    # Square Online embeds store ids as JSON in the order page (and sometimes
    # only on the shop homepage): "site_id":<num>, "user":{"id":<num>}, and
    # "shipping_location_ids":["<LOC>"].
    def find_ids(html: str) -> tuple[re.Match | None, re.Match | None, re.Match | None]:
        user = re.search(r'"user"\s*:\s*\{\s*"id"\s*:\s*(\d+)', html) or re.search(r"users/(\d+)", html)
        site = re.search(r'"site_id"\s*:\s*(\d+)', html) or re.search(r"sites/(\d+)", html)
        location = re.search(r'"[a-z_]*location_ids"\s*:\s*\[\s*"([A-Z0-9]{8,})"', html) or re.search(r"store-locations/([A-Z0-9]{8,})", html)
        return user, site, location
    user, site, location = find_ids(response.text)
    if not (user and site) and cached_html:
        user, site, location = find_ids(cached_html)
    if not (user and site):
        return []
    api_base = f"https://cdn5.editmysite.com/app/store/api/v28/editor/users/{user.group(1)}/sites/{site.group(1)}"
    candidate_ids = [location.group(1)] if location else []
    if not candidate_ids:
        candidate_ids = [loc["id"] for loc in get(f"{api_base}/store-locations", params={"per_page": 100, "valid": 1}).json().get("data", [])]
    if location and len(candidate_ids) == 1:
        # The id embedded in the page is often only one of several locations,
        # and not always the one holding the catalogue.
        try:
            candidate_ids += [loc["id"] for loc in get(f"{api_base}/store-locations", params={"per_page": 100, "valid": 1}).json().get("data", []) if loc.get("id") != candidate_ids[0]]
        except Exception:
            pass
    payload: dict[str, Any] = {}
    for location_id in candidate_ids:
        api = f"{api_base}/store-locations/{location_id}/products"
        base_params = {"page": 1, "per_page": 200, "include": "images,options,modifiers,attributes"}
        # Prefer pickup-fulfillable items, but a shop that never tagged its
        # catalogue for pickup returns an empty list rather than an error, so
        # fall back to the unfiltered catalogue instead of recording no menu.
        for params in ({**base_params, "fulfillments[]": "pickup"}, base_params):
            payload = get(api, params=params).json()
            if payload.get("data"):
                break
        if payload.get("data"):
            break
    out = []
    for product in payload.get("data", []):
        price = product.get("price") or {}
        cents = price.get("low_subunits")
        if not isinstance(cents, int) or cents <= 0:
            continue
        out.append(MenuItem(str(product.get("square_id") or product.get("site_product_id") or product.get("id")), str(product.get("name") or "Menu item").strip(), product.get("category", {}).get("name") if isinstance(product.get("category"), dict) else None, cents, cents, price.get("high_subunits"), product))
    return out


def extract_html_menu(url: str, platform: str) -> list[MenuItem]:
    response = get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    out: dict[str, MenuItem] = {}
    selectors = "a[href*='item-']" if platform == "toast" else "article, li, [class*='item'], [class*='product']"
    for node in soup.select(selectors):
        text = " ".join(node.get_text(" ", strip=True).split())
        prices = re.findall(r"\$\s*(\d{1,3}(?:\.\d{2})?)", text)
        if not prices or len(text) > 260:
            continue
        price = int(round(float(prices[-1]) * 100))
        name = re.sub(r"\s*\$\s*\d{1,3}(?:\.\d{2})?.*$", "", text).strip(" -·")
        if not name or len(name) < 2 or len(name) > 110:
            continue
        href = node.get("href") if hasattr(node, "get") else None
        stable = None
        if href:
            match = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27,36})", href, re.I)
            stable = match.group(1) if match else href
        stable = stable or hashlib.sha1(name.lower().encode()).hexdigest()[:20]
        out[stable] = MenuItem(stable, name, None, price, raw={"source": response.url})
    return list(out.values())


# ---------------------------------------------------------------------------
# A shop with no ordering platform often still prints its drink list as plain
# HTML. Those pages are worth reading, but to a parser a roaster's storefront
# looks exactly like a cafe menu: names beside prices in a grid. Every rule
# below exists to tell a $5 cappuccino from a $17 bag of beans.
SITE_MENU_LINK = re.compile(r"\bmenus?\b|\bdrinks?\b|\bcafe\b|\bcoffee\b|beverage|\bbar\b", re.I)
SITE_PRICE = re.compile(r"\$\s*(\d{1,3}(?:\.\d{1,2})?)(?!\d)")
# A size row writes the sign once ("$4.00 | 4.50 | 5.00"), so a bare decimal
# counts only in a row a signed price has already anchored; otherwise every
# phone number and street address on the page becomes a menu item.
SITE_BARE_PRICE = re.compile(r"(?<![\d.$])(\d{1,2}\.\d{2})(?![\d])")
SITE_JUNK = re.compile(
    r"gift ?card|subscri|newsletter|shipping|free deliver|follow us|copyright|privacy|"
    r"\bcart\b|sign ?up|log ?in|save \$|©|minimum|deposit|per person|catering|\bfees?\b|"
    r"gratuity|plus tax|starting at|order online|all rights|add to|sold out|compare|"
    r"unit price|regular price|sale price|original price|current price|\busd\b|\bper (?:lb|pound)\b",
    re.I)
SITE_TITLE_HINT = re.compile(r"title|item-?name|product-?name|\bname\b|heading", re.I)
SITE_SIZE = (r"small|medium|large|reg(?:ular)?|sm|med|lg|tall|grande|kids?|single|double|hot|"
             r"iced|ice|each|ea|[smlx]{1,2}|\d{1,2}(?:\.\d)?\s*(?:fl\.?\s*)?oz\.?|"
             r"\d{1,2}\s*(?:pc|piece|shots?|cups?)")
SITE_SIZE_ONLY = re.compile(rf"^(?:(?:{SITE_SIZE})\b[\s./|,\-–—]*)+$", re.I)
# Trailing size words repeat what the price cells already say ("Latte / 8 oz /
# 12 oz"); left in the name they defeat parse_size and split one item in two.
SITE_SIZE_TAIL = re.compile(rf"[\s./|,\-–—]*\b(?:{SITE_SIZE})\b[\s./|,\-–—]*$", re.I)
SITE_LETTER = re.compile(r"[A-Za-z]")
SITE_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
SITE_MAX_ROW = 200      # longer than this the block is prose, not a menu row
SITE_MAX_NAME = 70
SITE_MIN_CENTS = 100    # under a dollar it is an add-on: "Extra Shot .85"
SITE_MAX_CENTS = 2500   # over $25 it is retail: bags, whole cakes, catering boxes
# The plausibility gates. A storefront and a menu are the same markup, so a page
# must look like a menu on all three counts before any of its rows are believed.
SITE_MIN_ITEMS = 8
SITE_MEDIAN_CENTS = (250, 900)
SITE_MIN_DRINKS = 3
SITE_MIN_DRINK_SHARE = 0.10


def row_text(node: Any) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def row_lines(node: Any) -> list[str]:
    return [" ".join(line.split()) for line in node.get_text("\n", strip=True).split("\n") if line.strip()]


def row_prices(text: str) -> list[int]:
    found, seen = [], set()
    for match in list(SITE_PRICE.finditer(text)) + list(SITE_BARE_PRICE.finditer(text)):
        cents = int(round(float(match.group(1)) * 100))
        if cents not in seen:
            seen.add(cents)
            found.append(cents)
    return found


def strip_prices(text: str) -> str:
    text = SITE_BARE_PRICE.sub(" ", SITE_PRICE.sub(" ", text))
    return re.sub(r"\s{2,}", " ", text).strip(" .-–—·|/,:*+$&")


def is_item_name(text: str) -> bool:
    # Three letters in total rather than three in a row: "To Go" is a real item.
    return bool(text) and 2 < len(text) <= SITE_MAX_NAME and len(SITE_LETTER.findall(text)) >= 3 and not SITE_SIZE_ONLY.match(text)


def row_title(row: Any) -> str | None:
    """A title node inside the row beats the row's flattened text, which on most
    templates also carries the item's description."""
    for child in row.find_all(True):
        marker = " ".join(child.get("class") or []) + " " + (child.get("itemprop") or "")
        if child.name in SITE_HEADINGS or SITE_TITLE_HINT.search(marker):
            text = row_text(child)
            if not SITE_PRICE.search(text) and is_item_name(text):
                return text
    return None


def paired_heading(row: Any) -> str | None:
    """<h3>Latte</h3><p>8oz - $5.25</p> names the item. A heading followed by a
    run of priced siblings is a section header and must not become a name."""
    previous = row.find_previous_sibling(lambda tag: row_text(tag))
    if previous is None or previous.name not in SITE_HEADINGS:
        return None
    priced = 0
    for sibling in previous.find_next_siblings():
        if sibling.name in SITE_HEADINGS:
            break
        if SITE_PRICE.search(row_text(sibling)):
            priced += 1
    text = row_text(previous)
    return text if priced == 1 and is_item_name(text) else None


def neighbour_title(cell: Any) -> str | None:
    """Name for a price cell that carries no name of its own, as in a column of
    "$6.50 / small" divs sitting beside their item's own title div."""
    node = cell
    for _ in range(3):
        parent = node.parent
        if parent is None:
            return None
        found = titled = None
        for child in parent.find_all(True, recursive=False):
            if child is node:
                break
            text = row_text(child)
            if SITE_PRICE.search(text) or not is_item_name(text):
                continue
            found = text
            # A heading or title-classed node beside the price is the item's
            # name; a plain sibling is as often the item's description.
            marker = " ".join(child.get("class") or [])
            if child.name in SITE_HEADINGS or SITE_TITLE_HINT.search(marker):
                titled = text
            elif row_title(child):
                titled = row_title(child)
        if titled or found:
            return titled or found
        node = parent
    return None


def price_row(cell: Any) -> Any | None:
    """Smallest ancestor holding both the price cell and a name."""
    node = cell
    for _ in range(4):
        text = row_text(node)
        if len(text) > SITE_MAX_ROW:
            return None
        if is_item_name(strip_prices(text)):
            return node
        parent = node.parent
        if parent is None:
            return None
        # Climbing into a parent that already holds two named priced children
        # would fuse two menu items into one row carrying both their prices.
        named = sum(1 for child in parent.find_all(True, recursive=False)
                    if SITE_PRICE.search(row_text(child)) and is_item_name(strip_prices(row_text(child))))
        if named >= 2:
            return None
        node = parent
    return None


def size_prices(cells: list[Any]) -> list[tuple[int, str]]:
    """(cents, size label) pairs read from the innermost price cells, so a row
    that prices each size separately keeps the size the shop printed."""
    parts, seen = [], set()
    for cell in cells:
        for line in row_lines(cell):
            found = row_prices(line)
            label = strip_prices(line)
            if not SITE_SIZE_ONLY.match(label):
                label = ""
            for cents in found:
                if cents in seen:
                    continue
                seen.add(cents)
                parts.append((cents, label if len(found) == 1 else ""))
    return sorted(parts)


def site_menu_rows(html: str) -> list[tuple[str, list[tuple[int, str]]]]:
    """(name, [(cents, size label)]) for every priced row on one page.

    Menus put an item's name and its size prices in sibling elements at least as
    often as in one text node, so a row is grown outwards from the innermost
    node holding a price instead of matching a "name $price" string.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form", "select", "button"]):
        tag.decompose()
    for tag in soup.find_all("br"):
        tag.replace_with("\n")
    cells = [node for node in soup.find_all(True)
             if SITE_PRICE.search(row_text(node))
             and not any(SITE_PRICE.search(row_text(kid)) for kid in node.find_all(True))]
    rows: list[tuple[str, list[tuple[int, str]], str]] = []
    grouped: dict[int, tuple[Any, list[Any]]] = {}
    order: list[int] = []
    for cell in cells:
        priced = [line for line in row_lines(cell) if SITE_PRICE.search(line)]
        # One cell, several priced lines that each name themselves: a whole menu
        # section written as <br>-separated lines inside a single paragraph.
        if len(priced) > 1 and all(is_item_name(strip_prices(line)) for line in priced):
            for line in priced:
                name = SITE_SIZE_TAIL.sub("", strip_prices(line)).strip(" .-–—·|/,:*+$&")
                rows.append((name, [(cents, "") for cents in row_prices(line)], line))
            continue
        row = price_row(cell)
        key = id(row) if row is not None else id(cell)
        if key not in grouped:
            grouped[key] = (row, [])
            order.append(key)
        grouped[key][1].append(cell)
    for key in order:
        row, priced_cells = grouped[key]
        text = row_text(row if row is not None else priced_cells[0])
        name = (row_title(row) or paired_heading(row)) if row is not None else None
        name = name or strip_prices(text)
        if not is_item_name(name):
            name = neighbour_title(priced_cells[0]) or name
        name = SITE_SIZE_TAIL.sub("", name).strip(" .-–—·|/,:*+$&")
        rows.append((name, size_prices(priced_cells), text))
    return [(name, parts) for name, parts, text in rows
            if parts and is_item_name(name) and not SITE_JUNK.search(text) and not SITE_JUNK.search(name)]


def site_pages(website: str, limit: int = 4) -> list[tuple[str, str]]:
    """The homepage plus a few same-domain menu-ish pages, as (url, html)."""
    try:
        response = get(website)
    except Exception:
        return []
    pages = [(response.url, response.text)]
    soup = BeautifulSoup(response.text, "html.parser")
    seen = {response.url.rstrip("/")}
    for anchor in soup.find_all("a", href=True):
        href = urljoin(response.url, anchor.get("href")).split("#")[0]
        # A PDF menu is common and unreadable here; fetching it wastes the budget
        # of pages on a shop that may also have an HTML one.
        if urlparse(href).netloc != urlparse(response.url).netloc or href.lower().split("?")[0].endswith(".pdf"):
            continue
        if not SITE_MENU_LINK.search(f"{anchor.get_text(' ', strip=True)} {href}"):
            continue
        if href.rstrip("/") in seen or len(seen) > limit:
            continue
        seen.add(href.rstrip("/"))
        try:
            inner = get(href)
        except Exception:
            continue
        pages.append((inner.url, inner.text))
    return pages


def site_menu_is_plausible(menu: list[MenuItem]) -> bool:
    """True when the pages really read as a cafe menu.

    The three symptoms of a storefront, in order: too few rows to be a menu at
    all, a median price in bag territory rather than cup territory, and names
    that never say what a drink is. The last one also wants two different kinds
    of drink, because a shelf of "Ethiopia Coffee 12 oz" bags otherwise reads as
    a few cups of drip.
    """
    if len(menu) < SITE_MIN_ITEMS:
        return False
    median = statistics.median(entry.price_cents for entry in menu)
    if not SITE_MEDIAN_CENTS[0] <= median <= SITE_MEDIAN_CENTS[1]:
        return False
    kinds = []
    for entry in menu:
        is_drink, kind = classify_name(entry.name)
        # "Vanilla Mocha Cake" is a cake: the drink words in a bakery case must
        # not be what qualifies the page.
        if is_drink and kind and kind != "other" and not FOOD_ITEM.search(entry.name):
            kinds.append(kind)
    return (len(kinds) >= SITE_MIN_DRINKS and len(kinds) >= SITE_MIN_DRINK_SHARE * len(menu)
            and len(set(kinds)) >= 2)


def extract_site_menu(website: str) -> list[MenuItem]:
    """Drink prices published as plain HTML on a shop's own website.

    Returns nothing unless the pages clear site_menu_is_plausible: most shops
    with prices on their own site are roasters selling $17 bags, and a bag
    stored as a cup of coffee is worse for the compare view than a missing shop.
    """
    found: dict[str, MenuItem] = {}
    for url, html in site_pages(website):
        for name, parts in site_menu_rows(html):
            if RETAIL_PACKAGING.search(name):
                continue
            usable = [(cents, label) for cents, label in parts if SITE_MIN_CENTS <= cents <= SITE_MAX_CENTS]
            low = min((cents for cents, _ in usable), default=None)
            high = max((cents for cents, _ in usable), default=None)
            for index, (cents, label) in enumerate(usable):
                # The shop priced each size itself, so each size is its own item.
                # Where it named the sizes the name carries them and parse_size
                # can read them back; where it only listed prices the index keeps
                # the id stable as that size's price moves.
                stated = label and not re.search(rf"\b{re.escape(label)}\b", name, re.I)
                full = f"{name} {label}".strip() if stated else name
                stable = hashlib.sha1(full.lower().encode()).hexdigest()[:20]
                if len(usable) > 1 and not stated:
                    stable = f"{stable}-{index}"
                found.setdefault(stable, MenuItem(stable, full, None, cents, low, high, {"source": url}))
    menu = list(found.values())
    return menu if site_menu_is_plausible(menu) else []


def extract_jsonld_rating(html: str) -> tuple[float | None, int | None]:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "null")
        except Exception:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        for obj in stack:
            if isinstance(obj, dict) and isinstance(obj.get("aggregateRating"), dict):
                rating = obj["aggregateRating"]
                try:
                    return float(rating.get("ratingValue")), int(str(rating.get("ratingCount") or rating.get("reviewCount") or "0").replace(",", ""))
                except (TypeError, ValueError):
                    pass
    return None, None


def extract_modifiers(raw: dict[str, Any] | None) -> list[tuple[str | None, str, int]]:
    """Priced modifier choices, as (group, choice, cents).

    Square reports a product's own price in cents (``price.low_subunits``) but
    a modifier choice's upcharge in dollars (``0.75`` is 75 cents, ``1`` is a
    dollar), so the two cannot share a conversion. Only the declared modifier
    sets are read: walking the payload freely also collects cross-sell
    products and nested menu items, which then get stored as if a pastry were
    a milk option on a latte.
    """
    groups = ((raw or {}).get("modifiers") or {}).get("data") or []
    found: dict[tuple[str | None, str], int] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or "").strip() or None
        for choice in group.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            name = choice.get("name") or choice.get("label") or choice.get("display_name")
            price = choice.get("price")
            # bool is an int in Python, and a sold-out flag must not become a price.
            if not isinstance(name, str) or isinstance(price, bool) or not isinstance(price, (int, float)):
                continue
            cents = int(round(float(price) * 100))
            if 0 <= cents <= 5000:
                found[(group_name, name.strip())] = cents
    return sorted((group, choice, cents) for (group, choice), cents in found.items())


PAGE = 1000


def get_all(db: Supabase, table: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Every row, not the first page.

    PostgREST caps an unbounded response at 1000 rows and says so only in the
    Content-Range header, so a plain get() silently truncates. sync_shops read
    the shop table that way: past 1000 shops the rows beyond the cap would look
    undiscovered and every one of them would be inserted again as a duplicate.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = db.get(table, {**(params or {}), "offset": str(offset), "limit": str(PAGE)})
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        offset += PAGE


def sync_shops(db: Supabase, discovered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = get_all(db, "shops", {"select": "*"})
    by_osm = {shop.get("osm_id"): shop for shop in existing if shop.get("osm_id")}
    for row in discovered:
        old = by_osm.get(row["osm_id"])
        if old:
            db.patch("shops", f"id=eq.{old['id']}", row)
        else:
            created = db.post("shops", row)[0]
            by_osm[row["osm_id"]] = created
    return get_all(db, "shops", {"select": "*", "closed_at": "is.null"})


def resolve_source(shop: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    website = normalize_url(shop.get("website"))
    if not website:
        return None, None, None
    platform, source, cached = direct_link(website)
    name = shop["name"].lower()
    if not source and "sip" in name and shop["metro"] == "twin_cities":
        return "square", "https://sipcoffeebar.square.site/s/order", None
    if not source and "mad rooster" in name and shop["metro"] == "milwaukee":
        return "toast", "https://toast.app/r/mad-rooster-milwaukee-4401-w-greenfield-ave/order/r-2faf7892-e26a-4085-b0e1-c1f8d3bb845b", None
    return platform, source, cached


def collect_source(shop: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None, list[MenuItem], tuple[float | None, int | None]]:
    platform, source, cached = resolve_source(shop)
    website = normalize_url(shop.get("website"))
    if not platform or not source:
        # No ordering platform anywhere on the site. A few shops publish the
        # menu itself as HTML, which is the only remaining way to price them.
        if not website:
            return shop, None, None, [], (None, None)
        try:
            menu = extract_site_menu(website)
        except Exception as exc:
            print(f"Site menu failed for {shop['name']}: {exc}", file=sys.stderr)
            menu = []
        if not menu:
            return shop, None, None, [], (None, None)
        try:
            rating = extract_jsonld_rating(get(website).text)
        except Exception:
            rating = (None, None)
        # shops.platform rejects values outside the known ordering platforms
        # (see the retry in import_menu.py), and save_menu's patch is not
        # guarded, so a new label here would abort the whole run. The menu is
        # still recorded and scrape_status still becomes "collected".
        return shop, None, website, menu, rating
    try:
        if platform == "square":
            menu = extract_square(source, cached)
        else:
            menu = extract_html_menu(source, platform)
        home_html = get(website or source).text
        rating = extract_jsonld_rating(home_html)
        return shop, platform, source, menu, rating
    except Exception as exc:
        print(f"Collection failed for {shop['name']}: {exc}", file=sys.stderr)
        return shop, platform, source, [], (None, None)


def save_menu(db: Supabase, shop: dict[str, Any], platform: str | None, source: str | None, menu: list[MenuItem], rating: tuple[float | None, int | None]) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    status = "collected" if menu else ("unsupported" if not platform else "empty")
    db.patch("shops", f"id=eq.{shop['id']}", {"platform": platform, "last_checked_at": now, "scrape_status": status})
    if rating[0] is not None:
        db.post("ratings", {"shop_id": shop["id"], "source": "website", "rating": rating[0], "review_count": rating[1], "observed_at": now})
    existing = get_all(db, "items", {"select": "*", "shop_id": f"eq.{shop['id']}"})
    by_platform = {item["platform_item_id"]: item for item in existing}
    seen: set[str] = set()
    for entry in menu:
        seen.add(entry.platform_id)
        size_label, size_oz, confidence = parse_size(entry.name)
        is_drink, drink_type = refine_classification(entry.name, entry.category, entry.price_cents, size_oz)
        values = {"name": entry.name, "category": entry.category, "is_drink": is_drink, "drink_type": drink_type, "size_label": size_label, "size_oz": size_oz, "size_confidence": confidence, "last_seen": dt.date.today().isoformat(), "removed_at": None}
        item = by_platform.get(entry.platform_id)
        if item:
            db.patch("items", f"id=eq.{item['id']}", values)
        else:
            item = db.post("items", {**values, "shop_id": shop["id"], "platform_item_id": entry.platform_id})[0]
        if item.get("current_price_cents") != entry.price_cents:
            db.post("observations", {"item_id": item["id"], "observed_at": now, "price_cents": entry.price_cents, "price_low_cents": entry.low_cents, "price_high_cents": entry.high_cents, "price_channel": "direct", "available": True, "source_url": source, "raw": entry.raw})
        else:
            db.patch("items", f"id=eq.{item['id']}", {"last_checked_at": now, "last_seen": dt.date.today().isoformat()})
        # Any platform whose payload carries modifier sets, not just Square:
        # the compare view's oat-milk maths needs these wherever they exist.
        choices = extract_modifiers(entry.raw)
        if choices:
            prior = db.get("modifiers", {"select": "group_name,choice_name,price_delta_cents", "item_id": f"eq.{item['id']}", "order": "observed_at.desc", "limit": "500"})
            latest = {(row["group_name"], row["choice_name"], row["price_delta_cents"]) for row in prior}
            additions = [{"item_id": item["id"], "group_name": group, "choice_name": name, "price_delta_cents": cents, "observed_at": now} for group, name, cents in choices if (group, name, cents) not in latest]
            if additions:
                db.post("modifiers", additions)
    for item in existing:
        if item["platform_item_id"] not in seen and menu and not item.get("removed_at"):
            db.patch("items", f"id=eq.{item['id']}", {"removed_at": dt.date.today().isoformat()})


def main() -> None:
    db = Supabase()
    all_discovered = [shop for metro in METROS for shop in discover(metro)]
    shops = sync_shops(db, all_discovered)
    candidates = [shop for shop in shops if shop.get("website")]
    print(f"Checking {len(candidates)} shop websites for supported direct menus")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(collect_source, shop) for shop in candidates]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            shop, platform, source, menu, rating = future.result()
            save_menu(db, shop, platform, source, menu, rating)
            if menu:
                print(f"[{index}/{len(candidates)}] {shop['name']}: {len(menu)} items via {platform}")
    print("Collection complete")


if __name__ == "__main__":
    main()
