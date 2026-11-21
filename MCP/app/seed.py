"""Seed data: Bangkok restaurants, menus with nutrition, Shopee Mall products.

Prices in THB. Nutrition per serving so an agent can pick against a macro gap.
"""

import json
import re
from pathlib import Path

DEFAULT_LOCATION = {"lat": 13.7246, "lng": 100.5293}  # Silom, Bangkok

# Real Bangkok locations with prices and nutrition from the sources listed in the
# seed. Entries with price_source="simulated" use demo prices and nutrition estimates.
DATA = Path(__file__).parent / "data" / "restaurants.json"
RESTAURANT_PHOTOS = json.loads(DATA.with_name("restaurant_photos.json").read_text())
NUTRIENTS = ("calories", "protein_g", "carbs_g", "fat_g", "sodium_mg")


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
        "image_credit": RESTAURANT_PHOTOS[shop_id],
        "menu": [_item(shop_id, i, m) for i, m in enumerate(raw["menu"], 1)],
    }


def _item(shop_id: str, index: int, m: dict) -> dict:
    return {
        "item_id": f"m_{shop_id[2:]}_{index}",
        "shop_id": shop_id,
        "name": m["name"],
        "name_th": m.get("name_th"),
        "price_thb": m["price_thb"],
        **({"price_source": m["price_source"]} if "price_source" in m else {}),
        "nutrition": {k: m[k] for k in NUTRIENTS},
        "nutrition_source": m["nutrition_source"],
    }


RESTAURANTS = [_shop(r) for r in json.loads(DATA.read_text())]

# Shops are fictional. Product photos are served from app/static/products/.
# Licensed Wikimedia assets retain a source URL. Original demo images have no external source.
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
        None,
        "Dreamy Sleep Official",
    ),
    (
        "p_eyemask_basic",
        "Lightweight Travel Eye Mask (2-pack)",
        "sleep",
        59,
        4.3,
        "Nylon, elastic strap, folds flat for flights.",
        None,
        "Bangkok Travel Gear",
    ),
    (
        "p_eyemask_cotton",
        "Breathable Cotton Eye Mask, Adjustable Strap",
        "sleep",
        129,
        4.5,
        "Soft cotton, tie strap fits any head size.",
        None,
        "HomeRest Store",
    ),
    (
        "p_eyemask_silk",
        "Mulberry Silk Eye Mask with Lace Trim",
        "sleep",
        390,
        4.9,
        "22 momme silk, gentle on skin and lashes.",
        None,
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
    (
        "p_gel_eye_pads",
        "Reusable Cooling Gel Under-Eye Pads",
        "sleep",
        149,
        4.6,
        "Two crescent-shaped cooling gel eye pads. Chill before use and wipe clean afterward.",
        None,
        "Dreamy Sleep Official",
    ),
    (
        "p_neck_pillow",
        "Memory Foam Travel Neck Pillow",
        "sleep",
        329,
        4.5,
        "U-shaped pillow with a clasp and removable fabric cover.",
        None,
        "Bangkok Travel Gear",
    ),
    (
        "p_white_noise",
        "Compact White Noise Machine",
        "sleep",
        549,
        4.7,
        "USB-powered bedside speaker with white noise, rain and fan sounds.",
        None,
        "HomeRest Store",
    ),
    (
        "p_yoga_mat",
        "Non-Slip Yoga Mat 6 mm",
        "recovery",
        429,
        4.6,
        "Textured exercise mat for yoga, stretching and floor exercises.",
        None,
        "FitPro Sports",
    ),
    (
        "p_resistance_bands",
        "Loop Resistance Band Set (3 Pack)",
        "recovery",
        219,
        4.5,
        "Three closed-loop bands in light, medium and firm resistance.",
        None,
        "FitPro Sports",
    ),
    (
        "p_insulated_bottle",
        "Insulated Stainless Steel Water Bottle 750 ml",
        "recovery",
        399,
        4.8,
        "Double-wall bottle with a screw lid and carry loop.",
        None,
        "Bangkok Travel Gear",
    ),
    (
        "p_bluetooth_earbuds",
        "Wireless Bluetooth Earbuds with Charging Case",
        "electronics",
        699,
        4.6,
        "Compact earbuds with touch controls and a pocket-sized USB-C charging case.",
        None,
        "Siam Tech Supply",
    ),
    (
        "p_usb_c_power_bank",
        "USB-C Power Bank 10,000 mAh",
        "electronics",
        599,
        4.7,
        "Slim portable charger for phones, with USB-C input and output and a battery indicator.",
        None,
        "Siam Tech Supply",
    ),
    (
        "p_usb_c_charger",
        "USB-C Charger 30 W",
        "electronics",
        449,
        4.6,
        "Compact USB C charger with a two-pin wall plug and USB Power Delivery. Cable sold separately.",
        None,
        "Metro Gadget Store",
    ),
    (
        "p_bluetooth_speaker",
        "Compact Portable Bluetooth Speaker",
        "electronics",
        749,
        4.5,
        "Rechargeable wireless speaker with a fabric grille and carry loop.",
        None,
        "Siam Tech Supply",
    ),
    (
        "p_led_desk_lamp",
        "Rechargeable LED Desk Lamp",
        "electronics",
        549,
        4.6,
        "Adjustable reading lamp with three brightness levels and USB-C charging.",
        None,
        "Metro Gadget Store",
    ),
    (
        "p_wireless_mouse",
        "Silent Wireless Mouse",
        "electronics",
        349,
        4.5,
        "Three-button mouse with quiet clicks and an included USB receiver.",
        None,
        "Metro Gadget Store",
    ),
    (
        "p_canvas_tote",
        "Everyday Canvas Tote Bag",
        "lifestyle",
        229,
        4.6,
        "Cotton canvas shoulder bag with reinforced handles and an outer pocket.",
        None,
        "Everyday Studio",
    ),
    (
        "p_compact_umbrella",
        "Compact Travel Umbrella",
        "lifestyle",
        279,
        4.5,
        "Navy folding umbrella with a wrist strap and a slim carry sleeve.",
        None,
        "Bangkok Travel Gear",
    ),
    (
        "p_travel_mug",
        "Insulated Travel Mug 500 ml",
        "lifestyle",
        389,
        4.7,
        "Double-wall stainless steel coffee tumbler with a spill-resistant lid.",
        None,
        "Everyday Studio",
    ),
    (
        "p_a5_planner",
        "A5 Weekly Planner Notebook",
        "lifestyle",
        169,
        4.5,
        "Undated weekly planner with a cloth cover, elastic closure and ribbon bookmark.",
        None,
        "Everyday Studio",
    ),
    (
        "p_packing_cubes",
        "Travel Packing Cubes (3 Pack)",
        "lifestyle",
        359,
        4.7,
        "Three zippered luggage organizers with mesh panels for clothes and accessories.",
        None,
        "Bangkok Travel Gear",
    ),
    (
        "p_insulated_lunch_bag",
        "Insulated Lunch Bag",
        "lifestyle",
        259,
        4.6,
        "Zippered lunch tote with a wipe-clean insulated lining and carry handles.",
        None,
        "Everyday Studio",
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
        "image_path": f"/static/products/{pid}.jpg",
        "image_source": img,
    }
