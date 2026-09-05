#!/usr/bin/env python3
"""Regression cases for the platform menu readers in scripts/menu_sources.py.

Every case runs offline against a payload trimmed from the real response, so a
platform changing its shape shows up as a failure here rather than as a shop
quietly losing its menu. Run with: python scripts/test_menu_sources.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import extract_modifiers  # noqa: E402
from menu_sources import (  # noqa: E402
    cents, incentivio_options, incentivio_title, kyoo_items, next_data,
    pick_location, platform_of, same_place, spoton_sections, toast_guid,
    toast_price, toast_rows, toast_short_url,
)

# (url, expected platform). The four the daily collector already labels are
# pinned in test_classify.py; these are the ones only this module can read.
PLATFORM_CASES = [
    ("https://order.toasttab.com/online/alma", "toast"),
    ("https://toast.app/r/gray-fox/order/r-2faf7892-e26a-4085-b0e1-c1f8d3bb845b", "toast"),
    ("https://order.spoton.com/so-cafe-yoto-20313/minneapolis-mn/66a13621c2bcb0c08acba14c", "spoton"),
    ("https://order.incentivio.com/c/anodynecoffee", "incentivio"),
    ("https://www.kyoo.tech/order/merchants/CFBWC96K81379", "kyoo"),
    ("https://shop.square.site/s/order", None),
    ("https://example.com/menu", None),
]

# (url, expected guid, expected shortUrl)
TOAST_URL_CASES = [
    ("https://toast.app/r/mad-rooster/order/r-2faf7892-e26a-4085-b0e1-c1f8d3bb845b",
     "2faf7892-e26a-4085-b0e1-c1f8d3bb845b", None),
    ("https://order.toasttab.com/online/alma?guid=e7eab8d5-4f98-44eb-bb76-f60897726b2e",
     "e7eab8d5-4f98-44eb-bb76-f60897726b2e", "alma"),
    ("https://order.toasttab.com/online/haven-1201-n-van-buren-street", None, "haven-1201-n-van-buren-street"),
    # "online" is Toast's own path segment, never a restaurant.
    ("https://order.toasttab.com/online/", None, None),
]

# (amount, units per dollar, expected cents)
MONEY_CASES = [
    (4.75, 1, 475),        # Toast prices in dollars
    ("7.95", 1, 795),       # SpotOn prices in a decimal string
    (4750, 1000, 475),      # Incentivio prices in tenths of a cent
    (375, 100, 375),        # Square and Kyoo price in cents
    (0, 1, None),           # a free modifier is not a price
    (True, 1, None),        # a sold-out flag is an int in Python
    ("sold out", 1, None),
]

# A Toast item priced per size reports price: null and every size in prices.
TOAST_PRICE_CASES = [
    ({"price": 4.75, "prices": [4.75]}, (475, 475, 475)),
    ({"price": None, "prices": [3, 3.5]}, (300, 300, 350)),
    ({"price": None, "prices": []}, None),
    ({"price": 4.75, "prices": []}, (475, None, None)),
]

TOAST_MENUS = [{
    "name": "Cafe at Night",
    "groups": [{"name": "Beverages", "items": [
        {"guid": "i1", "name": "Latte", "price": None, "prices": [4.75, 6]},
        {"guid": "i2", "name": "Cappuccino", "price": 4.75, "prices": [4.75]},
        {"guid": "i3", "name": "Comment", "price": 0, "prices": []},
    ]}],
}]

# (shop name, listing name, metres, shop address, listing address, expected)
MATCH_CASES = [
    ("Haven Cafe", "Haven Cafe", 66, None, None, True),
    ("Buttered Tin", "The Buttered Tin - NE Minneapolis", 39, None, None, True),
    ("Haraz Coffee House", "Haraz Coffee - Milwaukee", 18, None, None, True),
    ("Dia Café", "DIA Cafe - Greendale 6601 Northway", 7, None, None, True),
    # Different shops that share a block and half a name.
    ("The Fix Cafe", "The Howe Daily Kitchen & Bar", 108, None, None, False),
    ("The High Hat", "The French Hen Cafe + Moonflower Pizza", 127, None, None, False),
    # A shared three-letter word is not a name.
    ("Mo's Irish Pub", "Mo's A Place for Steaks", 90, None, None, False),
    # A stated street number settles it before any name rule runs.
    ("Highland Cafe", "Highland Grill", 90, "2012 Ford Pkwy", "771 Cleveland Ave S", False),
    ("Highland Cafe", "Highland Cafe", 90, "2012 Ford Pkwy", "2012 Ford Parkway", True),
    # The same name across town is a different branch.
    ("Colectivo Coffee", "Colectivo Coffee", 4000, None, None, False),
]

# Anodyne's four cafes, as Incentivio reports them (coordinates) and as Kyoo
# reports Stone Creek's (a street address and nothing else).
BRANCHES = [
    {"title": "Bay View", "latitude": 42.9918, "longitude": -87.8866, "street": "2920 S Kinnickinnic Ave"},
    {"title": "Walker's Point", "latitude": 43.0255, "longitude": -87.9137, "street": "224 W Bruce St"},
    {"title": "Wauwatosa", "latitude": 43.0503, "longitude": -88.0062, "street": "7471 Harwood Ave"},
]
# (shop, whether the platform publishes coordinates, expected branch)
BRANCH_CASES = [
    ({"lat": 43.0503, "lng": -88.0062, "address": "7471 Harwood Ave"}, True, "Wauwatosa"),
    ({"lat": 42.9918, "lng": -87.8866, "address": None}, True, "Bay View"),
    ({"lat": 43.0503, "lng": -88.0062, "address": "7471 Harwood Ave"}, False, "Wauwatosa"),
    # No coordinates and no street number to go on: the first branch stands.
    ({"lat": None, "lng": None, "address": None}, False, "Bay View"),
    (None, True, "Bay View"),
]

SPOTON_HTML = (
    '<html><body><script id="__NEXT_DATA__" type="application/json">'
    '{"props":{"pageProps":{"menuData":['
    '{"name":"Limited Time","menuItems":[{"id":"a","name":"Miso Caramel Cold Brew","price":"7.95","inStock":true}]},'
    '{"name":"Lattes","menuItems":[{"id":"a","name":"Miso Caramel Cold Brew","price":"7.95","inStock":true},'
    '{"id":"b","name":"Classic Matcha","price":"7.95","inStock":true}]}]}}}'
    "</script></body></html>"
)

INCENTIVIO_ITEM = {
    "itemId": "abc", "price": 0, "title": "Bay View - AMERICANO",
    "displayInfo": [{"langCode": "EN", "title": "AMERICANO"}],
    "optionGroups": [
        {"displayInfo": [{"langCode": "EN", "title": "Size"}],
         "minItemSelections": 1, "maxItemSelections": 1,
         "items": [{"displayInfo": [{"langCode": "EN", "title": "8oz"}], "price": 4000},
                   {"displayInfo": [{"langCode": "EN", "title": "16oz"}], "price": 4500}]},
        {"displayInfo": [{"langCode": "EN", "title": "MILK CHOICE"}],
         "minItemSelections": 0, "maxItemSelections": 1,
         "items": [{"displayInfo": [{"langCode": "EN", "title": "OAT MILK"}], "price": 1000},
                   {"displayInfo": [{"langCode": "EN", "title": "2%"}], "price": 0}]},
    ],
}

KYOO_CATEGORY = {
    "name": "Hot Coffee", "items": [],
    "subcategories": [{"name": "Drip Coffee", "items": [{
        "id": "item1", "name": "Café Au Lait",
        "variations": [
            {"id": "v1", "name": "8 oz", "price_money": {"amount": 375},
             "modifier_lists": [{"name": "Milk", "modifiers": [
                 {"name": "Oat Milk", "price_money": {"amount": 100}},
                 {"name": "Whole", "price_money": {"amount": 0}}]}]},
            {"id": "v2", "name": "16 oz", "price_money": {"amount": 425}, "modifier_lists": []},
        ]}]}],
}


def main() -> None:
    failures: list[str] = []

    for url, platform in PLATFORM_CASES:
        got = platform_of(url)
        if got != platform:
            failures.append(f"platform_of({url!r}) = {got!r}, want {platform!r}")

    for url, guid, short in TOAST_URL_CASES:
        if toast_guid(url) != guid:
            failures.append(f"toast_guid({url!r}) = {toast_guid(url)!r}, want {guid!r}")
        if toast_short_url(url) != short:
            failures.append(f"toast_short_url({url!r}) = {toast_short_url(url)!r}, want {short!r}")

    for amount, per_dollar, want in MONEY_CASES:
        got = cents(amount, per_dollar)
        if got != want:
            failures.append(f"cents({amount!r}, {per_dollar}) = {got!r}, want {want!r}")

    for item, want in TOAST_PRICE_CASES:
        got = toast_price(item)
        if got != want:
            failures.append(f"toast_price({item}) = {got}, want {want}")

    toast = {entry.name: entry for entry in toast_rows(TOAST_MENUS, "POS")}
    if sorted(toast) != ["Cappuccino", "Latte"]:
        failures.append(f"toast_rows names = {sorted(toast)}, want ['Cappuccino', 'Latte']")
    elif (toast["Latte"].price_cents, toast["Latte"].high_cents, toast["Latte"].category) != (475, 600, "Beverages"):
        failures.append(f"toast_rows Latte = {toast['Latte']}")

    for shop, listing, metres, shop_address, listing_address, want in MATCH_CASES:
        got = same_place(shop, listing, metres, shop_address, listing_address)
        if got != want:
            failures.append(f"same_place({shop!r}, {listing!r}, {metres}) = {got}, want {want}")

    for shop, has_coords, want in BRANCH_CASES:
        got = pick_location(
            shop, BRANCHES,
            (lambda row: (row["latitude"], row["longitude"])) if has_coords else (lambda row: None),
            lambda row: row["street"],
        )
        if got["title"] != want:
            failures.append(f"pick_location({shop}, coords={has_coords}) = {got['title']!r}, want {want!r}")

    sections = spoton_sections(next_data(SPOTON_HTML))
    rows = {entry.platform_id: entry for entry in sections}
    if len(rows) != 2:
        failures.append(f"spoton rows = {len(rows)}, want 2 (one per item id)")
    elif rows["a"].category != "Limited Time":
        # An item listed twice keeps the section the shop leads with.
        failures.append(f"spoton category = {rows['a'].category!r}, want 'Limited Time'")

    for stored, want in [("AMERICANO", "Americano"), ("ARNIE'S DAY OFF", "Arnie's Day Off"), ("ARNIE\u2019S DAY OFF", "Arnie\u2019s Day Off"),
                         ("16oz ICED", "16oz ICED"), ("2%", "2%")]:
        got = incentivio_title({"displayInfo": [{"langCode": "EN", "title": stored}]})
        if got != want:
            failures.append(f"incentivio_title({stored!r}) = {got!r}, want {want!r}")
    sizes, modifiers = incentivio_options(INCENTIVIO_ITEM)
    if sizes != [("8oz", 400), ("16oz", 450)]:
        failures.append(f"incentivio sizes = {sizes}")
    # Incentivio stores every name in capitals; they are cased for display.
    if extract_modifiers(modifiers) != [("Milk Choice", "2%", 0), ("Milk Choice", "Oat Milk", 100)]:
        failures.append(f"incentivio modifiers = {extract_modifiers(modifiers)}")

    kyoo = {entry.name: entry for entry in kyoo_items(KYOO_CATEGORY, None)}
    if sorted(kyoo) != ["Café Au Lait (16 oz)", "Café Au Lait (8 oz)"]:
        failures.append(f"kyoo names = {sorted(kyoo)}")
    elif (kyoo["Café Au Lait (8 oz)"].price_cents, kyoo["Café Au Lait (8 oz)"].category) != (375, "Drip Coffee"):
        failures.append(f"kyoo row = {kyoo['Café Au Lait (8 oz)']}")
    elif extract_modifiers(kyoo["Café Au Lait (8 oz)"].raw) != [("Milk", "Oat Milk", 100), ("Milk", "Whole", 0)]:
        failures.append(f"kyoo modifiers = {extract_modifiers(kyoo['Café Au Lait (8 oz)'].raw)}")

    for line in failures:
        print(f"FAIL {line}")
    total = (len(PLATFORM_CASES) + 2 * len(TOAST_URL_CASES) + len(MONEY_CASES)
             + len(TOAST_PRICE_CASES) + len(MATCH_CASES) + len(BRANCH_CASES) + 12)
    print(f"{total - len(failures)}/{total} cases pass")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
