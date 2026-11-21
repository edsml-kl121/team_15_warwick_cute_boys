"""A visitor's own health history (profile, meals, wearables) uploaded as one JSON document.

The upload is stored as-is, folded into the visitor's profile goals, merged into the food log,
and summarised for the coach so recommendations use the person's real habits.
"""
from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MEAL_LABELS = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}
RECENT_DAYS = 7


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
