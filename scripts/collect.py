#!/usr/bin/env python3
"""Collect public, direct-order coffee shop menus without delivery marketplaces."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
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
DIRECT_HOSTS = ("square.site", "squareup.com", "square.link", "toast.app", "toasttab.com", "order.spoton.com")
BLOCKED_HOSTS = ("ubereats.com", "doordash.com", "order.online", "grubhub.com", "clover.com", "chownow.com")


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
    r"https?://[A-Za-z0-9._~%-]*(?:square\.site|squareup\.com|square\.link|toasttab\.com|toast\.app|order\.spoton\.com)[A-Za-z0-9._~%!$&'()*+,;=:@/?#-]*",
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
    r"whole bean|\bbeans\b|\bground\b|\bbags?\b|\blbs?\b|\bpounds?\b|prepack|"
    r"k.?cups?\b|\bgallons?\b|\bbox\b|traveler|\bscoop\b|liqueur|subscription|"
    r"gift ?card|\bmerch\b|\bmugs?\b|tumbler|\bfilters?\b",
    re.I,
)
# Bakery words, by contrast, double as drink flavours ("Cheese Cake Cold Brew",
# "Cinnamon Roll Latte"), so they only disqualify an item that reached no
# named espresso or brew rule.
FOOD_ITEM = re.compile(
    r"\bcakes?\b|\brolls?\b|\bmuffins?\b|\bcookies?\b|\bscones?\b|croissant|"
    r"\bbagels?\b|\bdo(?:ugh)?nuts?\b|brownie|\bpastr|sandwich|\btoast\b|"
    r"\bbars?\b|\bpies?\b|\bloaf\b|biscuit|danish|quiche|burrito|\bwraps?\b",
    re.I,
)
# Blended drinks are drinks, but a shake is not a latte and a frappe is not
# drip; keeping them out of the named buckets keeps the compare view honest.
BLENDED = re.compile(r"\bshakes?\b|frapp|smoothie|\bmalt\b|\bslush", re.I)
DRINK_KINDS = [
    # Caramel latte is its own bucket and must beat the generic "latte",
    # "macchiato" and "mocha" rules, which the same names also match.
    ("caramel_latte", r"(?:caramel|carmel)\W+(?:\w+\W+){0,3}?(?:latte|macchiato)|"
                      r"(?:latte|macchiato)\W+(?:\w+\W+){0,3}?(?:caramel|carmel)"),
    ("cold_brew", r"cold brew|nitro"),
    ("cappuccino", r"cappuccino"),
    ("americano", r"americano"),
    # Macchiato and cortado are espresso drinks. Without them a plain
    # "Macchiato" matched no rule at all and was stored as not-a-drink.
    ("espresso", r"espresso|cortado|macchiato|\bristretto\b|\bdoppio\b"),
    ("mocha", r"mocha"),
    ("latte", r"latte|cafe au lait|café au lait"),
    # A bare "Coffee", "Hot Coffee" or "Coffee of the Day" is the drip cup on
    # most menus. This rule is broad, so it is the one the bakery guard covers.
    ("drip", r"drip|pour.?over|brewed coffee|batch brew|\bcoffee\b"),
    ("chai", r"chai"),
    ("tea", r"\btea\b|matcha"),
]
BROAD_KINDS = {"drip"}


def classify_name(name: str, category: str | None = None) -> tuple[bool, str | None]:
    text = f"{name} {category or ''}".lower()
    if RETAIL_PACKAGING.search(text):
        return False, None
    if BLENDED.search(text):
        return True, "other"
    for kind, pattern in DRINK_KINDS:
        if re.search(pattern, text):
            if kind in BROAD_KINDS and FOOD_ITEM.search(text):
                return False, None
            return True, kind
    if FOOD_ITEM.search(text):
        return False, None
    is_drink = bool(re.search(r"coffee|drink|beverage|iced|hot|lemonade|smoothie", text))
    return is_drink, "other" if is_drink else None


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


def sync_shops(db: Supabase, discovered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = db.get("shops", {"select": "*"})
    by_osm = {shop.get("osm_id"): shop for shop in existing if shop.get("osm_id")}
    for row in discovered:
        old = by_osm.get(row["osm_id"])
        if old:
            db.patch("shops", f"id=eq.{old['id']}", row)
        else:
            created = db.post("shops", row)[0]
            by_osm[row["osm_id"]] = created
    return db.get("shops", {"select": "*", "closed_at": "is.null"})


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
    if not platform or not source:
        return shop, None, None, [], (None, None)
    try:
        if platform == "square":
            menu = extract_square(source, cached)
        else:
            menu = extract_html_menu(source, platform)
        home_html = get(normalize_url(shop.get("website")) or source).text
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
    existing = db.get("items", {"select": "*", "shop_id": f"eq.{shop['id']}"})
    by_platform = {item["platform_item_id"]: item for item in existing}
    seen: set[str] = set()
    for entry in menu:
        seen.add(entry.platform_id)
        is_drink, drink_type = classify_name(entry.name, entry.category)
        size_label, size_oz, confidence = parse_size(entry.name)
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
