from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BANGKOK = ZoneInfo("Asia/Bangkok")
DEMO_DATE = "2026-11-21"
PROFILE = {
    "name": "Ploy", "location": "Silom, Bangkok", "member_since": "Nov 2026",
    "goals": {"sleep_minutes": 420, "deep_minutes": 90, "protein_g": 90, "kcal": 1900,
              "active_minutes": 20, "steps": 8000, "carbs_g": 230, "fat_g": 63},
    "preferences": {"food": "Healthy Thai, mild spice", "home": "Sathorn Soi 8", "work": "Silom"},
    "connections": [
        {"app": name, "connected": True, "shares": shares} for name, shares in [
            ("Shopee", ["Shopping and food listings"]), ("WHOOP", ["Sleep", "Recovery"]),
            ("Apple Health", ["Steps", "Workouts"]), ("Google Calendar", ["Calendar"]),
            ("Apple Calendar", ["Calendar"]), ("Apple Fitness", ["Workout summaries"]),
            ("Google Maps", ["Walking routes"]),
        ]
    ],
}
SLEEP = {
    "minutes": 310, "deep_minutes": 58, "goal_minutes": 90, "shortfall_minutes": 32,
    "start": "00:30", "end": "05:40", "short_nights": 3, "source": "WHOOP",
    "events": [{"at": "05:40", "label": "Room got bright"}, {"at": "02:35", "label": "3 h with no deep sleep"}],
    "totals": {"deep": 58, "rem": 60, "light": 187, "awake": 5},
    "timeline": [["light", 20], ["deep", 35], ["light", 30], ["deep", 23], ["rem", 17],
                 ["light", 60], ["rem", 22], ["light", 50], ["rem", 21], ["light", 27], ["awake", 5]],
}
RECOVERY = {"percent": 64, "note": "Take it easy · HRV below your usual level", "bars": [78, 71, 82, 59, 73, 67, 64]}
ACTIVITY = {"steps": 2140, "steps_goal_pct": 27, "active_minutes": 3, "sitting_hours": 9}
DINNER = {"dish": "Grilled chicken salad", "kcal": 400, "protein_g": 35,
          "why": "A high-protein dinner that fits your remaining calories."}
NUTRIENTS = ("kcal", "protein_g", "carbs_g", "fat_g")
FOOD = [
    ("07:40", "Breakfast", "Greek yogurt, granola and banana", 420, 11, 60, 16, "photo"),
    ("13:10", "Lunch", "Pad kra pao gai with fried egg", 690, 38, 53, 29, "photo"),
    ("16:00", "Snack", "Fresh mango", 150, 1, 37, 0, "chat"),
]


def seed(date):
    return deepcopy({
        "profile": PROFILE, "date": date,
        "day_data": {date: {"sleep": SLEEP, "recovery": RECOVERY, "activity": ACTIVITY}},
        "food": [dict(zip(("time", "meal", "dish", *NUTRIENTS, "source"), row)) | {"id": f"seed-{i}", "date": date}
                 for i, row in enumerate(FOOD)],
        "bookings": {}, "reminders": {}, "sessions": {}, "orders": {}, "clock": None,
    })


class Clock:
    def __init__(self, pinned=None):
        self.pinned = datetime.fromisoformat(pinned) if pinned else None

    def now(self, state=None):
        if state and state["clock"]:
            return datetime.fromisoformat(state["clock"])
        now = self.pinned or datetime.now(BANGKOK)
        return now.astimezone(BANGKOK) if now.tzinfo else now.replace(tzinfo=BANGKOK)


def after_minutes(time, minutes):
    return (datetime.fromisoformat(f"{DEMO_DATE}T{time}") + timedelta(minutes=minutes)).strftime("%H:%M")
