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
    "twin_cities": (44.85, -93.35, 45.10, -92.98),
}
DIRECT_HOSTS = ("square.site", "toast.app", "toasttab.com", "order.spoton.com")
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


def direct_link(home_url: str) -> tuple[str | None, str | None, str | None]:
    try:
        response = get(home_url)
    except Exception:
        return None, None, None
    candidates = [response.url]
    soup = BeautifulSoup(response.text, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = urljoin(response.url, anchor.get("href"))
        if any(host in href.lower() for host in DIRECT_HOSTS):
            candidates.append(href)
    for candidate in candidates:
        host = urlparse(candidate).netloc.lower()
        if any(blocked in host for blocked in BLOCKED_HOSTS):
            continue
        if "square.site" in host:
            return "square", candidate, response.text if candidate == response.url else None
        if "toast.app" in host or "toasttab.com" in host:
            return "toast", candidate, None
        if "order.spoton.com" in host:
            return "spoton", candidate, None
    return None, None, None


def classify_name(name: str, category: str | None = None) -> tuple[bool, str | None]:
    text = f"{name} {category or ''}".lower()
    kinds = [
        ("cold_brew", r"cold brew|nitro"), ("cappuccino", r"cappuccino"),
        ("americano", r"americano"), ("espresso", r"espresso|cortado"),
        ("mocha", r"mocha"), ("latte", r"latte|cafe au lait|café au lait"),
        ("drip", r"drip|pour.?over|brewed coffee|batch brew"),
        ("chai", r"chai"), ("tea", r"\btea\b|matcha"),
    ]
    for kind, pattern in kinds:
        if re.search(pattern, text):
            return True, kind
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
    order_url = url if "/s/order" in url else url.rstrip("/") + "/s/order"
    response = get(order_url)
    html = cached_html or response.text
    ids = {
        "user": re.search(r"users/(\d+)", html),
        "site": re.search(r"sites/(\d+)", html),
        "location": re.search(r"store-locations/([A-Z0-9]{8,})", html),
    }
    if not all(ids.values()):
        return []
    api = f"https://cdn5.editmysite.com/app/store/api/v28/editor/users/{ids['user'].group(1)}/sites/{ids['site'].group(1)}/store-locations/{ids['location'].group(1)}/products"
    payload = get(api, params={"page": 1, "per_page": 200, "include": "images,options,modifiers,attributes", "fulfillments[]": "pickup"}).json()
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


def square_modifiers(raw: dict[str, Any] | None) -> list[tuple[str, int]]:
    """Extract priced choices from Square's nested public product response."""
    found: dict[str, int] = {}
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            name = value.get("name") or value.get("title")
            price = value.get("price") or value.get("price_delta") or value.get("price_money")
            cents = None
            if isinstance(price, dict):
                cents = price.get("amount") or price.get("subunits") or price.get("low_subunits")
            elif isinstance(price, int):
                cents = price
            if isinstance(name, str) and isinstance(cents, int) and 0 <= cents <= 1000:
                found[name.strip()] = cents
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(raw)
    return sorted(found.items())


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
        if platform == "square":
            prior = db.get("modifiers", {"select": "name,price_delta_cents", "item_id": f"eq.{item['id']}", "order": "observed_at.desc", "limit": "100"})
            latest = {(row["name"], row["price_delta_cents"]) for row in prior}
            additions = [{"item_id": item["id"], "name": name, "price_delta_cents": cents, "observed_at": now} for name, cents in square_modifiers(entry.raw) if (name, cents) not in latest]
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
