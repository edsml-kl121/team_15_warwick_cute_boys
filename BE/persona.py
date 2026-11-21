"""A visitor's own health history (profile, meals, wearables) uploaded as one JSON document.

The upload is stored as-is, folded into the visitor's profile goals, merged into the food log,
and summarised for the coach so recommendations use the person's real habits.
"""
from collections import Counter
from datetime import date
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MEAL_LABELS = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}
RECENT_DAYS = 7


def history_date(row):
    value = row.get("date") or row.get("timestamp") or row.get("start_time")
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _activity_measure(row, *keys):
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            continue
        value = _number(value, None)
        if value is not None and isfinite(value) and value >= 0:
            return round(value)
    return None


def activity_history(persona, through):
    """Return the seven most recent dates with recorded activity."""
    persona = persona or {}
    days = {}
    for row in persona.get("wearable_daily", []):
        day = history_date(row)
        if day is None or day > through:
            continue
        readings = {
            "steps": _activity_measure(row, "steps"),
            "active_minutes": _activity_measure(row, "active_minutes"),
            "calories_burned_kcal": _activity_measure(row, "calories_burned_kcal", "calories_burned",
                                                     "total_calories_kcal", "total_energy_kcal"),
            "active_calories_kcal": _activity_measure(row, "active_calories_kcal", "active_energy_kcal", "active_kcal"),
        }
        present = {key: value for key, value in readings.items() if value is not None}
        if present:
            entry = days.setdefault(day, {"date": day.isoformat(), "workouts": []})
            entry.update(present)
            if row.get("source") == "imported_sample":
                entry["source"] = "imported_sample"

    for row in persona.get("workouts", []):
        day = history_date(row)
        if day is None or day > through:
            continue
        name = row.get("name") or row.get("workout_type") or row.get("sport") or row.get("type")
        days.setdefault(day, {"date": day.isoformat(), "workouts": []})["workouts"].append({
            "name": name.strip().replace("_", " ") if isinstance(name, str) and name.strip() else "Workout",
            **({"location": row["location"]} if isinstance(row.get("location"), str) and row["location"].strip() else {}),
            **({"source": "imported_sample"} if row.get("source") == "imported_sample" else {}),
            **({"calories_estimated": True} if row.get("calories_estimated") is True else {}),
            "minutes": _activity_measure(row, "duration_minutes", "duration_min"),
            "calories_burned_kcal": _activity_measure(row, "calories_burned_kcal", "active_calories_kcal",
                                                     "calories_burned", "calories_kcal", "energy_kcal", "kcal"),
        })
    return [days[day] for day in sorted(days, reverse=True)[:RECENT_DAYS]]


class PersonaProfile(BaseModel):
    model_config = ConfigDict(extra="allow")
    persona_id: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=1, max_length=60)
    daily_calorie_target: int | None = Field(default=None, gt=0, le=9999)
    macro_targets: dict[str, float] = Field(default_factory=dict)
    cuisine_prefs: list[str] = Field(default_factory=list, max_length=20)
    favorite_dishes: list[str] = Field(default_factory=list, max_length=20)
    connected_sources: list[str] = Field(default_factory=list, max_length=32)
    home_area: dict[str, Any] = Field(default_factory=dict)


class Persona(BaseModel):
    model_config = ConfigDict(extra="allow")
    profile: PersonaProfile
    as_of: str | None = Field(default=None, max_length=40)
    window: list[str] = Field(default_factory=list, max_length=2)
    food_history_log: list[dict[str, Any]] = Field(default_factory=list, max_length=3000)
    wearable_daily: list[dict[str, Any]] = Field(default_factory=list, max_length=400)
    workouts: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    weights: list[dict[str, Any]] = Field(default_factory=list, max_length=400)
    body_composition_scans: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _app_name(source):
    return source.replace("_", " ").title()


def apply_to_profile(profile, persona):
    """Return a new app profile with the persona's name, targets, tastes and connections."""
    source = persona["profile"]
    macros = source.get("macro_targets") or {}
    goals = {
        **profile["goals"],
        **({"kcal": int(source["daily_calorie_target"])} if source.get("daily_calorie_target") else {}),
        **{key: int(_number(macros[key])) for key in ("protein_g", "carbs_g", "fat_g") if _number(macros.get(key)) > 0},
    }
    area = source.get("home_area") or {}
    tastes = ", ".join([*source.get("cuisine_prefs", []), *source.get("favorite_dishes", [])])
    connected = {item["app"] for item in profile["connections"] if item["connected"]}
    imported = [{"app": _app_name(name), "connected": True, "shares": ["Imported history"]}
                for name in source.get("connected_sources", []) if _app_name(name) not in connected]
    location = ", ".join(str(area[key]) for key in ("district", "city") if area.get(key))
    return {
        **profile,
        "name": source["display_name"][:60],
        "location": location[:120] or profile["location"],
        "goals": goals,
        "preferences": {**profile["preferences"], **({"food": tastes[:240]} if tastes else {})},
        "connections": [*profile["connections"], *imported][:32],
    }


def _meal_source(entry):
    if entry.get("source") == "imported_sample":
        return "imported_sample", None
    if entry.get("channel") == "shopee_food_order":
        return "shopee_food", (entry.get("order") or {}).get("restaurant")
    return ("photo" if (entry.get("agent_call") or {}).get("logged_via") == "photo" else "chat"), None


def persona_meals(persona, date):
    """Food log entries for one date, in the app's food-entry shape."""
    meals = []
    for entry in (persona or {}).get("food_history_log", []):
        if entry.get("date") != date:
            continue
        totals = entry.get("meal_totals") or {}
        items = entry.get("items") or []
        source, place = _meal_source(entry)
        meals.append({
            "id": f"persona-{entry.get('log_id', len(meals))}",
            "date": date,
            "time": str(entry.get("timestamp", ""))[11:16],
            "meal": MEAL_LABELS.get(entry.get("meal_time"), "Meal"),
            "dish": entry.get("meal_name") or " + ".join(item.get("dish_name", "") for item in items[:3]) or "Meal",
            "kcal": round(_number(totals.get("calories"))),
            "protein_g": round(_number(totals.get("protein_g"))),
            "carbs_g": round(_number(totals.get("carbs_g"))),
            "fat_g": round(_number(totals.get("fat_g"))),
            "source": source,
            **({"place": place} if place else {}),
        })
    return sorted(meals, key=lambda meal: meal["time"])


def recommendation_context(persona):
    """A compact view of the person's habits for the coach, small enough for a tool result."""
    if not persona:
        return {"available": False}
    profile = persona["profile"]
    log = persona.get("food_history_log", [])
    recent = set(sorted({entry.get("date") for entry in log if entry.get("date")})[-RECENT_DAYS:])
    restaurants = Counter((entry.get("order") or {}).get("restaurant") for entry in log
                          if entry.get("channel") == "shopee_food_order")
    dishes = Counter(item.get("dish_name") for entry in log for item in entry.get("items", []))
    weights = [row for row in persona.get("weights", []) if _number(row.get("weight_kg"), None) is not None]
    keep = ("age", "sex", "height_cm", "weight_kg", "body_goal", "pace_kg_per_week", "daily_calorie_target",
            "macro_targets", "diet_preset", "cuisine_prefs", "favorite_dishes", "medical_conditions",
            "allergies", "home_area", "summary_30d")
    return {
        "available": True,
        "as_of": persona.get("as_of"),
        "profile": {key: profile[key] for key in keep if key in profile},
        "recent_meals": [
            {"date": entry.get("date"), "meal": entry.get("meal_time"), "name": entry.get("meal_name"),
             "source": entry.get("source"),
             "restaurant": (entry.get("order") or {}).get("restaurant"),
             "calories": (entry.get("meal_totals") or {}).get("calories"),
             "protein_g": (entry.get("meal_totals") or {}).get("protein_g")}
            for entry in log if entry.get("date") in recent
        ],
        "top_restaurants": [name for name, _ in restaurants.most_common(5) if name],
        "top_dishes": [name for name, _ in dishes.most_common(8) if name],
        "recent_wearables": persona.get("wearable_daily", [])[-RECENT_DAYS:],
        "recent_workouts": persona.get("workouts", [])[-5:],
        "weight_trend": {"first": weights[0], "last": weights[-1]} if weights else None,
        "latest_body_scan": (persona.get("body_composition_scans") or [None])[-1],
    }


# Proactive recommendations -------------------------------------------------

def _dish_catalog(persona):
    """Each dish the person has eaten, with nutrition per serving, how often, and where they ordered it."""
    dishes = {}
    for entry in (persona or {}).get("food_history_log", []):
        restaurant = (entry.get("order") or {}).get("restaurant")
        for item in entry.get("items", []):
            name, nutrition = item.get("dish_name"), item.get("nutrition") or {}
            kcal, protein = _number(nutrition.get("calories")), _number(nutrition.get("protein_g"))
            if not name or kcal <= 0:
                continue
            dish = dishes.setdefault(name, {"dish": name, "kcal": round(kcal), "protein_g": round(protein),
                                            "cuisine": item.get("cuisine"), "count": 0, "restaurants": Counter(),
                                            "meal_times": Counter()})
            dish["count"] += 1
            dish["meal_times"][entry.get("meal_time")] += 1
            if restaurant:
                dish["restaurants"][restaurant] += 1
    return dishes


def pick_meal(persona, protein_gap, kcal_left, default, meal_time="dinner", exclude=(), min_protein=None):
    """Choose a dish the person already likes that closes the protein gap within the calories left."""
    profile = (persona or {}).get("profile", {})
    favourites = {name.casefold() for name in profile.get("favorite_dishes", [])}
    cuisines = {name.casefold() for name in profile.get("cuisine_prefs", [])}
    budget = max(kcal_left, 450)
    floor = min(25, max(protein_gap, 15)) if min_protein is None else min_protein
    candidates = [dish for dish in _dish_catalog(persona).values()
                  if dish["protein_g"] >= floor and dish["kcal"] <= budget
                  and dish["dish"] not in exclude]
    if not candidates:
        return default

    def score(dish):
        favourite = any(name in dish["dish"].casefold() or dish["dish"].casefold() in name for name in favourites)
        return (dish["meal_times"][meal_time] > 0, 2 * favourite + (str(dish["cuisine"]).casefold() in cuisines),
                dish["count"], dish["protein_g"] / dish["kcal"])

    best = max(candidates, key=score)
    reasons = []
    if best["restaurants"]:
        place, times = best["restaurants"].most_common(1)[0]
        reasons.append(f"you've ordered it {times}× from {place}" if times > 1 else f"you've had it from {place}")
    elif best["count"] > 1:
        reasons.append(f"you've logged it {best['count']} times")
    reasons.append(f"{best['protein_g']} g protein for {best['kcal']} kcal fits the {max(0, round(kcal_left))} kcal you have left")
    return {"dish": best["dish"], "kcal": best["kcal"], "protein_g": best["protein_g"],
            "why": ("A familiar pick: " + "; ".join(reasons) + ".")[:240]}


def weekly_recap(persona, goals, days=RECENT_DAYS):
    """Averages over the last logged days, one insight, and the question to ask next."""
    log = (persona or {}).get("food_history_log", [])
    dates = sorted({entry.get("date") for entry in log if entry.get("date")})[-days:]
    if not dates:
        return None
    window = [entry for entry in log if entry.get("date") in dates]
    total = lambda key: sum(_number((entry.get("meal_totals") or {}).get(key)) for entry in window)
    count = len(dates)
    orders = [entry["order"] for entry in window if entry.get("channel") == "shopee_food_order" and entry.get("order")]
    spend = Counter()
    for order in orders:
        spend[order.get("restaurant")] += _number(order.get("total_thb"))
    wearables = [row for row in persona.get("wearable_daily", []) if row.get("date") in dates and row.get("steps")]
    weights = [row for row in persona.get("weights", []) if _number(row.get("weight_kg"), None) is not None]
    recap = {
        "kind": "weekly_recap", "days": count, "from": dates[0], "to": dates[-1],
        "kcal": round(total("calories") / count), "kcal_goal": goals.get("kcal"),
        "protein_g": round(total("protein_g") / count), "protein_goal": goals.get("protein_g"),
        "sodium_mg": round(total("sodium_mg") / count),
        "orders": len(orders), "spend_thb": round(sum(spend.values())),
        "top_restaurant": spend.most_common(1)[0][0] if spend else None,
        "steps": round(sum(row["steps"] for row in wearables) / len(wearables)) if wearables else None,
        "steps_goal": goals.get("steps"),
        "weight_change_kg": round(_number(weights[-1]["weight_kg"]) - _number(weights[0]["weight_kg"]), 1) if len(weights) > 1 else None,
    }
    over = recap["kcal"] - (recap["kcal_goal"] or recap["kcal"])
    if over > 150:
        insight = f"You averaged {over:,} kcal a day over your target, mostly at dinner."
    elif recap["sodium_mg"] > 2300:
        insight = f"Calories were close to target, but sodium averaged {recap['sodium_mg']:,} mg a day."
    else:
        insight = "You stayed close to your targets this week. Nice."
    recap["insight"] = insight
    return recap


def plan_day(persona, goals):
    """Three familiar meals that together land near the calorie and protein targets."""
    kcal_goal, protein_goal = goals.get("kcal", 2000), goals.get("protein_g", 90)
    plan, used = [], set()
    shares = (("breakfast", 0.25), ("lunch", 0.35), ("dinner", 0.4))
    for meal_time, share in shares:
        dish = pick_meal(persona, protein_goal * share, kcal_goal * share, None, meal_time, used, min_protein=15)
        if dish:
            used.add(dish["dish"])
            plan.append({"meal": MEAL_LABELS[meal_time], **dish})
    return plan


def lighter_orders(persona, limit=3):
    """Dishes the person has ordered on Shopee Food with the most protein per calorie."""
    ordered = [dish for dish in _dish_catalog(persona).values() if dish["restaurants"] and dish["protein_g"] >= 15]
    ranked = sorted(ordered, key=lambda dish: dish["protein_g"] / dish["kcal"], reverse=True)[:limit]
    return [{"dish": dish["dish"], "kcal": dish["kcal"], "protein_g": dish["protein_g"],
             "restaurant": dish["restaurants"].most_common(1)[0][0]} for dish in ranked]
