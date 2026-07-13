"""Curated subset of Shopify's real, published Standard Product Taxonomy for the
Edit Products Category picker.

Every gid/path below was verified against Shopify's own published taxonomy data
(github.com/Shopify/product-taxonomy, dist/en/categories.txt) — nothing here is
invented. This matters because Category (unlike product_type) is meant to be
one real Shopify taxonomy node per product, and edits here are staged to sync
to Shopify eventually; a made-up category would silently be wrong forever.

Shopify's public taxonomy has NO branch for commercial/wholesale bakery or
food-service equipment (it's a consumer-retail taxonomy) — there is no
"Donut Proofers", "Commercial Mixers", or "Commercial Fryers" node, and
"Bakery" only exists under Food Items (edible goods, not equipment). So most
of this catalog's real product types (donut robots, sheeters, proofers,
depositors, glazers) have no precise match. Per product decision: fall back to
the closest REAL parent node rather than inventing a specific one — every
option offered here, including the coarse fallbacks, is a genuine node you can
look up in Shopify's taxonomy browser (https://shopify.github.io/product-taxonomy/).

Structure: each GROUP is a real Shopify parent category (itself selectable, as
the coarse fallback for anything in that group with no more specific match);
each group's `options` are real, more specific child leaf nodes actually
relevant to this catalog.
"""
from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class CategoryOption(TypedDict):
    name: str
    gid: str
    path: str


class CategoryGroup(TypedDict):
    group: str
    gid: str
    path: str
    options: List[CategoryOption]


CATEGORY_TAXONOMY: List[CategoryGroup] = [
    {
        "group": "Kitchen Appliances",
        "gid": "gid://shopify/TaxonomyCategory/hg-11-7",
        "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances",
        "options": [
            {"name": "Deep Fryers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-7",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Deep Fryers"},
            {"name": "Air Fryers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-53",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Air Fryers"},
            {"name": "Ovens", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-35",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Ovens"},
            {"name": "Chest Freezers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-20-1",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Freezers > Chest Freezers"},
            {"name": "Upright Freezers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-20-3",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Freezers > Upright Freezers"},
            {"name": "Drawer Freezers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-20-2",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Freezers > Drawer Freezers"},
            {"name": "Commercial Refrigerators", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-41-1",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Refrigerators > Commercial Refrigerators"},
            {"name": "Mini Refrigerators", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-41-2",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Refrigerators > Mini Refrigerators"},
            {"name": "Stand Mixers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-17-2-2",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Mixers & Blenders > Food Mixers > Stand Mixers"},
            {"name": "Hand Mixers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-17-2-1",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Mixers & Blenders > Food Mixers > Hand Mixers"},
            {"name": "Countertop Blenders", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-17-1-2",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Mixers & Blenders > Food Blenders > Countertop Blenders"},
            {"name": "Immersion Blenders", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-17-1-3",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Mixers & Blenders > Food Blenders > Immersion Blenders"},
            {"name": "Chafing Dishes", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-19-1",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Warmers > Chafing Dishes"},
            {"name": "Food Heat Lamps", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-19-2",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Warmers > Food Heat Lamps"},
            {"name": "Steam Tables", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-19-4",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Warmers > Steam Tables"},
            {"name": "Warming Drawers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-19-7",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Warmers > Warming Drawers"},
            {"name": "Soup Kettles", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-19-6",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Warmers > Soup Kettles"},
            {"name": "Rice Keepers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-19-3",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Warmers > Rice Keepers"},
            {"name": "Ice Makers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-28",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Ice Makers"},
            {"name": "Ice Cream Makers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-26",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Ice Cream Makers"},
            {"name": "Ice Crushers & Shavers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-27",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Ice Crushers & Shavers"},
            {"name": "Electric Griddles & Grills", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-10",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Electric Griddles & Grills"},
            {"name": "Gas Griddles", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-23",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Gas Griddles"},
            {"name": "Dishwashers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-9",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Dishwashers"},
            {"name": "Food Processors", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-54",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Processors"},
            {"name": "Donut Makers", "gid": "gid://shopify/TaxonomyCategory/hg-11-7-46-2",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Toasters & Grills > Donut Makers"},
        ],
    },
    {
        "group": "Kitchen Appliance Accessories",
        "gid": "gid://shopify/TaxonomyCategory/hg-11-6",
        "path": "Home & Garden > Kitchen & Dining > Kitchen Appliance Accessories",
        "options": [
            {"name": "Deep Fryer Accessories", "gid": "gid://shopify/TaxonomyCategory/hg-11-6-5",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliance Accessories > Deep Fryer Accessories"},
            {"name": "Food Mixer Accessories", "gid": "gid://shopify/TaxonomyCategory/hg-11-6-36",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliance Accessories > Food Mixer Accessories"},
            {"name": "Freezer Accessories", "gid": "gid://shopify/TaxonomyCategory/hg-11-6-12",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliance Accessories > Freezer Accessories"},
            {"name": "Refrigerator Accessories", "gid": "gid://shopify/TaxonomyCategory/hg-11-6-24",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliance Accessories > Refrigerator Accessories"},
            {"name": "Cooktop, Oven & Range Accessories", "gid": "gid://shopify/TaxonomyCategory/hg-11-6-3",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Appliance Accessories > Cooktop, Oven & Range Accessories"},
        ],
    },
    {
        "group": "Kitchen Tools & Utensils",
        "gid": "gid://shopify/TaxonomyCategory/hg-11-8",
        "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils",
        "options": [
            {"name": "Kitchen Scales", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-80",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Kitchen Scales"},
            {"name": "Cooking Thermometers", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-17",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Cooking Thermometers"},
            {"name": "Cooking Thermometer Accessories", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-16",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Cooking Thermometer Accessories"},
            {"name": "Ladles", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-46",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Ladles"},
            {"name": "Kitchen Scrapers", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-42",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Kitchen Scrapers"},
            {"name": "Cookie Cutters", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-14",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Cookie Cutters"},
            {"name": "Aprons", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-1",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Aprons"},
            {"name": "Mixing Bowls", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-50",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Mixing Bowls"},
            {"name": "Tongs", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-76",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Tongs"},
            {"name": "Spatulas", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-69",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Spatulas"},
            {"name": "Scoops", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-65",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Scoops"},
            {"name": "Whisks", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-77",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Whisks"},
            {"name": "Cutting Boards", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-21",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Cutting Boards"},
            {"name": "Colanders & Strainers", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-12",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Colanders & Strainers"},
            {"name": "Funnels", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-34",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Funnels"},
            {"name": "Cake Decorating Supplies", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-6",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Cake Decorating Supplies"},
            {"name": "Pastry Blenders", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-56",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Pastry Blenders"},
            {"name": "Pastry Cloths", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-57",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Pastry Cloths"},
            {"name": "Rolling Pins", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-62",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Rolling Pins"},
            {"name": "Rolling Pin Accessories", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-61",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Rolling Pin Accessories"},
            {"name": "Dough Wheels", "gid": "gid://shopify/TaxonomyCategory/hg-11-8-23",
             "path": "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Dough Wheels"},
        ],
    },
    {
        "group": "Cookware & Bakeware",
        "gid": "gid://shopify/TaxonomyCategory/hg-11-2",
        "path": "Home & Garden > Kitchen & Dining > Cookware & Bakeware",
        "options": [
            {"name": "Bakeware", "gid": "gid://shopify/TaxonomyCategory/hg-11-2-1",
             "path": "Home & Garden > Kitchen & Dining > Cookware & Bakeware > Bakeware"},
            {"name": "Bakeware Accessories", "gid": "gid://shopify/TaxonomyCategory/hg-11-2-2",
             "path": "Home & Garden > Kitchen & Dining > Cookware & Bakeware > Bakeware Accessories"},
            {"name": "Cookware", "gid": "gid://shopify/TaxonomyCategory/hg-11-2-3",
             "path": "Home & Garden > Kitchen & Dining > Cookware & Bakeware > Cookware"},
            {"name": "Cookware Accessories", "gid": "gid://shopify/TaxonomyCategory/hg-11-2-5",
             "path": "Home & Garden > Kitchen & Dining > Cookware & Bakeware > Cookware Accessories"},
        ],
    },
    {
        "group": "Food Storage",
        "gid": "gid://shopify/TaxonomyCategory/hg-11-4",
        "path": "Home & Garden > Kitchen & Dining > Food Storage",
        "options": [
            {"name": "Food Storage Containers", "gid": "gid://shopify/TaxonomyCategory/hg-11-4-6",
             "path": "Home & Garden > Kitchen & Dining > Food Storage > Food Storage Containers"},
            {"name": "Bread Boxes & Bags", "gid": "gid://shopify/TaxonomyCategory/hg-11-4-1",
             "path": "Home & Garden > Kitchen & Dining > Food Storage > Bread Boxes & Bags"},
            {"name": "Food Container Covers", "gid": "gid://shopify/TaxonomyCategory/hg-11-4-4",
             "path": "Home & Garden > Kitchen & Dining > Food Storage > Food Container Covers"},
            {"name": "Food Storage Bags", "gid": "gid://shopify/TaxonomyCategory/hg-11-4-5",
             "path": "Home & Garden > Kitchen & Dining > Food Storage > Food Storage Bags"},
            {"name": "Food Wraps", "gid": "gid://shopify/TaxonomyCategory/hg-11-4-7",
             "path": "Home & Garden > Kitchen & Dining > Food Storage > Food Wraps"},
        ],
    },
    {
        "group": "Food Service",
        "gid": "gid://shopify/TaxonomyCategory/bi-8",
        "path": "Business & Industrial > Food Service",
        "options": [
            {"name": "Bakery Boxes", "gid": "gid://shopify/TaxonomyCategory/bi-8-1",
             "path": "Business & Industrial > Food Service > Bakery Boxes"},
            {"name": "Food Service Carts", "gid": "gid://shopify/TaxonomyCategory/bi-8-9",
             "path": "Business & Industrial > Food Service > Food Service Carts"},
            {"name": "Food Service Baskets", "gid": "gid://shopify/TaxonomyCategory/bi-8-8",
             "path": "Business & Industrial > Food Service > Food Service Baskets"},
            {"name": "Ice Bins", "gid": "gid://shopify/TaxonomyCategory/bi-8-12",
             "path": "Business & Industrial > Food Service > Ice Bins"},
            {"name": "Plate & Dish Warmers", "gid": "gid://shopify/TaxonomyCategory/bi-8-13",
             "path": "Business & Industrial > Food Service > Plate & Dish Warmers"},
            {"name": "Take-Out Containers", "gid": "gid://shopify/TaxonomyCategory/bi-8-15",
             "path": "Business & Industrial > Food Service > Take-Out Containers"},
            {"name": "Tilt Skillets", "gid": "gid://shopify/TaxonomyCategory/bi-8-16",
             "path": "Business & Industrial > Food Service > Tilt Skillets"},
            {"name": "Bus Tubs", "gid": "gid://shopify/TaxonomyCategory/bi-8-2",
             "path": "Business & Industrial > Food Service > Bus Tubs"},
        ],
    },
    {
        "group": "Retail",
        "gid": "gid://shopify/TaxonomyCategory/bi-22",
        "path": "Business & Industrial > Retail",
        "options": [
            {"name": "Retail Display Cases", "gid": "gid://shopify/TaxonomyCategory/bi-22-7",
             "path": "Business & Industrial > Retail > Retail Display Cases"},
        ],
    },
    {
        "group": "Industrial Storage",
        "gid": "gid://shopify/TaxonomyCategory/bi-13",
        "path": "Business & Industrial > Industrial Storage",
        "options": [
            {"name": "Industrial Shelving", "gid": "gid://shopify/TaxonomyCategory/bi-13-2",
             "path": "Business & Industrial > Industrial Storage > Industrial Shelving"},
        ],
    },
    {
        "group": "Carts & Islands",
        "gid": "gid://shopify/TaxonomyCategory/fr-5",
        "path": "Furniture > Carts & Islands",
        "options": [
            {"name": "Utility & Storage Carts", "gid": "gid://shopify/TaxonomyCategory/fr-5-1-3",
             "path": "Furniture > Carts & Islands > Carts > Utility & Storage Carts"},
        ],
    },
]


def category_options() -> List[Dict[str, Any]]:
    """Flat list of selectable options for the picker: every group header
    (the coarse real fallback) plus every leaf beneath it, in taxonomy order.
    """
    out: List[Dict[str, Any]] = []
    for grp in CATEGORY_TAXONOMY:
        out.append({"name": grp["group"], "gid": grp["gid"], "path": grp["path"], "group": grp["group"]})
        for opt in grp["options"]:
            out.append({**opt, "group": grp["group"]})
    return out
