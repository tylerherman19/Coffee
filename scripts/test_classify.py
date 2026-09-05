#!/usr/bin/env python3
"""Regression cases for the collector's classifier and its source detection.

The classifier cases are real rows from the live items table that were once
classified wrong. The platform cases pin which ordering hosts count as a
direct menu. Run with: python scripts/test_classify.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import classify_name, platform_of, refine_classification  # noqa: E402

# (name, category, expected is_drink, expected drink_type)
NAME_CASES = [
    # The item's own name outranks its section header.
    ("Latte", "Espresso", True, "latte"),
    ("Mocha", "Espresso", True, "mocha"),
    ("Drip Coffee", "Espresso", True, "drip"),
    ("Mulled Citrus Chai (8oz)", "Tea/Chai & Tea Lattes", True, "chai"),
    ("Almond Pear Sweet Foam Iced Matcha (12 oz)", "Tea/Chai & Tea Lattes", True, "tea"),
    ("Hot Tea", "Up Coffee - Drinks", True, "tea"),
    ("Cafe Finca (house drip, Oaxaca MX)", "Drip & Cold Brew", True, "drip"),
    # A "Non-Coffee" header must not name a coffee kind.
    ("Italian Soda", "Non-Coffee", True, "other"),
    ("Hot Chocolate", "Not Coffee", True, "other"),
    # A bakery word after the drink word is a pastry; before it, a flavour.
    ("Mocha Chip Rawr Bar", "Rawr Bars", False, None),
    ("Cheese Cake Cold Brew", None, True, "cold_brew"),
    ("Carrot Cake Latte", None, True, "latte"),
    ("Cinnamon Toast Latte", None, True, "latte"),
    ("Pecan Pie", "Espresso Shots", False, None),
    ("Scratch Matcha Roll Cake", "Okashi", False, None),
    # Upcharges are not cups.
    ("Extra Shot Espresso", "Online Menu", False, None),
    ("Shot of Espresso", "Menu", False, None),
    ("Shot Espresso Extra", "Online Menu", False, None),
    ("Coffee Flavor Shot", "Online Menu", False, None),
    ("Red Eye (add a shot of espresso)", "Coffee / Tea", False, None),
    ("Add Flavor", None, False, None),
    # ...but a real single espresso is.
    ("Espresso Shot", "Coffee, Espresso, Chai", True, "espresso"),
    ("Espresso", "Drinks", True, "espresso"),
    # Blended and boozy drinks are drinks, just not the cup being ranked.
    ("Blended Chai Latte", "Tea, Cocoa & More", True, "other"),
    ("Frozen Caramel Latte (12oz)", "Cold Coffee/Frozen Lattes", True, "other"),
    ("Turtle Mocha Caribou Cooler® Blended Beverage", "Signature", True, "other"),
    ("Frozen Cookies & Cream", "Tea, Cocoa & More", True, "other"),
    ("Espresso Martini", "Online Menu", True, "other"),
    ("Matchatini", None, True, "other"),
    # ...and "frozen" alone never turns a bakery case into one.
    ("TBT Freshly Frozen Cinnamon Rolls", "TBT Freshly Frozen Products", False, None),
    ("Rehorst Vodka Btl", None, False, None),
    # Retail, merch and catering.
    ("Vero Cappuccino Glass", "Online Menu", False, None),
    ("Pre Pack Tea", None, False, None),
    ("Catering Coffee", "Online Menu", False, None),
    ("Ethiopia Guji Hambela Natural SS 12oz", "Featured Coffee", True, "drip"),
    # Yogurt is food, a yogurt drink is not.
    ("Ayran Original Yogurt Drink", "Bottled Drinks", True, "other"),
    # A cookie under a "Cookies" header stays a cookie.
    ("Lemonade", "Cookies", False, None),
    # Long-standing behaviour that must not regress.
    ("Caramel Macchiato", "Espresso", True, "espresso"),
    ("Salted Caramel Latte", None, True, "caramel_latte"),
    ("Cold Brew", "Classic", True, "cold_brew"),
    ("Americano", "Menu", True, "americano"),
    ("Cappuccino", None, True, "cappuccino"),
]

# (name, category, price_cents, size_oz, expected is_drink, expected drink_type)
PRICE_CASES = [
    ("Vanilla", "Drinks", 75, None, False, None),            # syrup pump
    ("Extra Yogurt", "Fruit Smoothies", 75, None, False, None),
    ("Honest Kids Juice", "More Beverages/Juice", 100, None, True, "other"),
    ("Big Train Spiced Chai", "Online Menu", 2499, None, False, None),
    ("The Crowd Pleaser", "Whittier - Drinks", 3500, None, False, None),
    ("XXL Iced Latte 64oz", "Menu", 3500, 64.0, False, None),
    ("Ethiopia Guji Hambela Natural SS 12oz", "Featured Coffee", 1800, None, False, None),
    ("Latte", "Espresso", 525, 12.0, True, "latte"),
    ("Coffee of the Day", None, 150, None, True, "drip"),
]


# (url, expected platform). None means "not a direct menu we collect".
PLATFORM_CASES = [
    # ChowNow bills the shop rather than marking its menu up, so it is a
    # direct platform. All three host shapes appear in the wild.
    ("https://www.chownow.com/order/30815/locations/45570", "chownow"),
    ("https://direct.chownow.com/order/21463/locations/31082", "chownow"),
    ("https://order.chownow.com/order/4638/locations", "chownow"),
    # Delivery marketplaces mark the menu up and stay blocked.
    ("https://www.doordash.com/store/patricks-12345", None),
    ("https://www.ubereats.com/store/ginkgo", None),
    ("https://www.grubhub.com/restaurant/cuppa-java", None),
    ("https://order.online/store/x", None),
    ("https://shop.square.site/s/order", "square"),
    ("https://order.toasttab.com/online/x", "toast"),
    # Clover online ordering is white-label with the merchant's own prices:
    # unblocked 2026-09-05 after retesting the public menu API.
    ("https://www.clover.com/online-ordering/x", "clover"),
    ("https://order.spoton.com/x", "spoton"),
    ("https://example.com/menu", None),
]


def main() -> None:
    failures: list[str] = []
    for url, platform in PLATFORM_CASES:
        got = platform_of(url)
        if got != platform:
            failures.append(f"platform_of({url!r}) = {got!r}, want {platform!r}")
    for name, category, is_drink, drink_type in NAME_CASES:
        got = classify_name(name, category)
        if got != (is_drink, drink_type):
            failures.append(f"classify_name({name!r}, {category!r}) = {got}, want {(is_drink, drink_type)}")
    for name, category, price, size, is_drink, drink_type in PRICE_CASES:
        got = refine_classification(name, category, price, size)
        if got != (is_drink, drink_type):
            failures.append(f"refine_classification({name!r}, {category!r}, {price}, {size}) = {got}, want {(is_drink, drink_type)}")
    for line in failures:
        print(f"FAIL {line}")
    total = len(NAME_CASES) + len(PRICE_CASES) + len(PLATFORM_CASES)
    print(f"{total - len(failures)}/{total} cases pass")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
