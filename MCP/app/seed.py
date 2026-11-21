"""Small deterministic data set for the hackathon demo."""

DEMO_PHONE = "+16502013595"

RESTAURANTS = [
    ("s_easy_health", "Easy Health", "Sathorn", "healthy", 13.721, 100.535, ["Grilled Chicken Breast Salad", 220, 400, 35]),
    ("s_salad_factory", "Salad Factory", "Silom Complex (B floor)", "healthy", 13.728, 100.535, ["Grilled Chicken Breast Salad", 245, 410, 36]),
    ("s_mk_restaurants", "MK Restaurants", "Silom Complex", "suki", 13.728, 100.535, ["Suki Set", 299, 550, 28]),
    ("s_go_ang", "Go-Ang Kaomunkai Pratunam", "Pratunam 2 (Ratchadamri)", "thai", 13.746, 100.541, ["Chicken Rice", 80, 620, 30]),
    ("s_som_tam", "Som Tam Nua", "Siam Square Soi 5", "thai_isan", 13.746, 100.533, ["Grilled Chicken with Papaya Salad", 180, 430, 33]),
    ("s_jok_prince", "Jok Prince", "Bang Rak (Charoen Krung)", "thai", 13.719, 100.514, ["Pork Rice Porridge", 70, 350, 19]),
    ("s_thipsamai_pad", "Thipsamai Pad Thai", "Pratu Phi (original)", "thai", 13.751, 100.505, ["Pad Thai", 120, 580, 20]),
    ("s_rung_rueang", "Rung Rueang Pork Noodle", "Sukhumvit 26", "thai", 13.730, 100.569, ["Pork Noodle Soup", 90, 480, 25]),
    ("s_yayoi", "Yayoi", "Silom Complex", "japanese", 13.728, 100.535, ["Grilled Salmon Set", 269, 610, 34]),
    ("s_massilia", "Massilia", "Ruamrudee", "italian", 13.739, 100.550, ["Chicken Caesar Salad", 295, 460, 31]),
    ("s_holey_artisan", "Holey Artisan Bakery", "Suan Phlu", "cafe", 13.718, 100.541, ["Chicken Sandwich", 180, 470, 27]),
]


def restaurants(phone: str = DEMO_PHONE):
    result = []
    for shop_id, name, branch, cuisine, lat, lng, dish in RESTAURANTS:
        menu = [{"id": f"m_{shop_id[2:]}_1", "name": dish[0], "price_thb": dish[1], "calories": dish[2], "protein_g": dish[3]}]
        result.append({"shop_id": shop_id, "name": name, "branch": branch, "cuisine": cuisine,
                       "address": f"{branch}, Bangkok", "phone": phone, "lat": lat, "lng": lng, "menu": menu})
    return result


PRODUCTS = [
    ("p_eyemask", "Cooling Eye Mask", "sleep", "Dreamy Sleep Official", 199, 4.8),
    ("p_eyemask_basic", "Basic Eye Mask", "sleep", "Bangkok Travel Gear", 59, 4.4),
    ("p_eyemask_cotton", "Cotton Eye Mask", "sleep", "HomeRest Store", 129, 4.6),
    ("p_eyemask_silk", "Silk Eye Mask", "sleep", "Silk Lane Boutique", 390, 4.9),
    ("p_curtain", "Blackout Curtain", "sleep", "HomeRest Store", 590, 4.7),
    ("p_earplug", "Sleep Earplugs", "sleep", "Dreamy Sleep Official", 129, 4.5),
    ("p_nasal", "Nasal Strips", "sleep", "Bangkok Travel Gear", 249, 4.3),
    ("p_magnesium", "Magnesium Supplement", "recovery", "Recovery Lab", 450, 4.7),
    ("p_foamroller", "Foam Roller", "recovery", "Recovery Lab", 350, 4.6),
]


def products(base_url: str = ""):
    return [{"id": p[0], "name": p[1], "category": p[2], "shop": p[3], "price_thb": p[4], "rating": p[5],
             "image_url": f"{base_url}/static/products/{p[0]}.jpg"} for p in PRODUCTS]
