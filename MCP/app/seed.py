"""Seed data: Bangkok restaurants, menus with nutrition, Shopee Mall products.

Prices in THB. Nutrition per serving so an agent can pick against a macro gap.
"""

import json
import re
from pathlib import Path

IMG = "https://images.unsplash.com/{}?w=600&q=70"

DEFAULT_LOCATION = {"lat": 13.7246, "lng": 100.5293}  # Silom, Bangkok

# Real Bangkok branches researched Nov 2026 (prices from LINE MAN/Wongnai or the
# restaurant's own site). Nutrition is "official" only where the restaurant
# publishes it; everything else is a per-serving estimate. See app/data/restaurants.json.
DATA = Path(__file__).parent / "data" / "restaurants.json"
NUTRIENTS = ("calories", "protein_g", "carbs_g", "fat_g", "sodium_mg")
CUISINE_IMG = {
    "healthy": "photo-1512621776951-a57141f2eefd",
    "suki": "photo-1547592180-85f173990554",
    "thai": "photo-1569058242253-92a9c755a0ec",
    "thai_isan": "photo-1559314809-0d155014e29e",
    "japanese": "photo-1579871494447-9811cf80d66c",
    "italian": "photo-1513104890138-7c749659a591",
    "cafe": "photo-1509440159596-0249088772ff",
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _shop(raw: dict) -> dict:
    shop_id = "s_" + "_".join(_slug(raw["name"].split("(")[0]).split("_")[:2])
    return {
        "shop_id": shop_id,
        "name": raw["name"],
        "branch": raw["branch"],
        "address": raw["address"],
        "phone": raw.get("phone"),  # E.164, for agent/Twilio booking calls
        "cuisine": raw["cuisine"],
        "rating": raw["rating"],
        "lat": raw["lat"],
        "lng": raw["lng"],
        "image_url": IMG.format(CUISINE_IMG.get(raw["cuisine"], CUISINE_IMG["thai"])),
        "menu": [_item(shop_id, i, m) for i, m in enumerate(raw["menu"], 1)],
    }


def _item(shop_id: str, index: int, m: dict) -> dict:
    return {
        "item_id": f"m_{shop_id[2:]}_{index}",
        "shop_id": shop_id,
        "name": m["name"],
        "name_th": m.get("name_th"),
        "price_thb": m["price_thb"],
        "nutrition": {k: m[k] for k in NUTRIENTS},
        "nutrition_source": m["nutrition_source"],
    }


RESTAURANTS = [_shop(r) for r in json.loads(DATA.read_text())]

# Shops are fictional. All product photos are from Wikimedia Commons, each checked by eye,
# and copied into app/static/products/ (Wikimedia throttles bursts of hotlinked images).
# Licenses: public domain (Schlafmaske, Sleep_mask), CC0 (Hotel_bedroom_windows),
# CC BY 2.0 (Handmade_sleepmasks_eyemasks_Paris), CC BY-SA 3.0 (Masque_de_sommeil,
# A_pair_of_orange_foam_earplugs, Magnesium_tablets), CC BY-SA 4.0 (Nasenpflaster_aus_Seide,
# Walek_do_masazu). Credit the Commons uploaders if shown publicly.
WIKIMEDIA = "https://upload.wikimedia.org/wikipedia/commons/"
MALL_PRODUCTS = [
    # (product_id, name, category, price_thb, rating, description, image, shop)
    (
        "p_eyemask",
        "3D Contoured Sleep Eye Mask",
        "sleep",
        199,
        4.8,
        "Blocks 100% light, zero pressure on eyes.",
        WIKIMEDIA + "thumb/e/e0/Schlafmaske.jpg/500px-Schlafmaske.jpg",
        "Dreamy Sleep Official",
    ),
    (
        "p_eyemask_basic",
        "Lightweight Travel Eye Mask (2-pack)",
        "sleep",
        59,
        4.3,
        "Nylon, elastic strap, folds flat for flights.",
        WIKIMEDIA + "6/6f/Sleep_mask.jpg",
        "Bangkok Travel Gear",
    ),
    (
        "p_eyemask_cotton",
        "Breathable Cotton Eye Mask, Adjustable Strap",
        "sleep",
        129,
        4.5,
        "Soft cotton, tie strap fits any head size.",
        WIKIMEDIA + "thumb/6/6a/Masque_de_sommeil.jpg/500px-Masque_de_sommeil.jpg",
        "HomeRest Store",
    ),
    (
        "p_eyemask_silk",
        "Mulberry Silk Eye Mask with Lace Trim",
        "sleep",
        390,
        4.9,
        "22 momme silk, gentle on skin and lashes.",
        WIKIMEDIA
        + "thumb/1/1a/Handmade_sleepmasks_eyemasks_Paris%2C_France.jpg/"
        + "500px-Handmade_sleepmasks_eyemasks_Paris%2C_France.jpg",
        "Silk Lane Boutique",
    ),
    (
        "p_curtain",
        "Blackout Curtain 140x220cm (2 panels)",
        "sleep",
        590,
        4.6,
        "Thermal blackout, blocks street light.",
        WIKIMEDIA + "thumb/2/28/Hotel_bedroom_windows_%28Unsplash%29.jpg/500px-Hotel_bedroom_windows_%28Unsplash%29.jpg",
        "HomeRest Store",
    ),
    (
        "p_earplug",
        "Soft Foam Earplugs (20 pairs)",
        "sleep",
        129,
        4.7,
        "32dB noise reduction.",
        WIKIMEDIA + "thumb/8/88/A_pair_of_orange_foam_earplugs.jpg/500px-A_pair_of_orange_foam_earplugs.jpg",
        "Bangkok Travel Gear",
    ),
    (
        "p_nasal",
        "Nasal Strips Extra Strength (30)",
        "sleep",
        249,
        4.4,
        "Opens nasal passages, reduces snoring.",
        WIKIMEDIA
        + "thumb/1/19/Nasenpflaster_aus_Seide_%28Audemu%29.jpg/"
        + "500px-Nasenpflaster_aus_Seide_%28Audemu%29.jpg",
        "Dreamy Sleep Official",
    ),
    (
        "p_magnesium",
        "Magnesium Glycinate 400mg (60 tablets)",
        "recovery",
        450,
        4.5,
        "Supports sleep quality and muscle recovery.",
        WIKIMEDIA + "thumb/1/19/Magnesium_tablets.jpg/500px-Magnesium_tablets.jpg",
        "VitaLife Thailand",
    ),
    (
        "p_foamroller",
        "High-Density Textured Foam Roller 45cm",
        "recovery",
        350,
        4.6,
        "Post-workout muscle release.",
        WIKIMEDIA + "thumb/1/1e/Wa%C5%82ek_do_masa%C5%BCu.jpg/500px-Wa%C5%82ek_do_masa%C5%BCu.jpg",
        "FitPro Sports",
    ),
]


def product(row: tuple) -> dict:
    pid, name, category, price, rating, desc, img, shop = row
    return {
        "product_id": pid,
        "name": name,
        "shop": shop,
        "category": category,
        "price_thb": price,
        "rating": rating,
        "description": desc,
        "image_path": f"/static/products/{pid}.jpg",  # self-hosted copy of image_source
        "image_source": img,
    }
