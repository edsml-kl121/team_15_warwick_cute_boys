import os
from copy import deepcopy

from demo import PROFILE
from persona import history_date


DATASET = "ploy-v1"
RECORDS = {"meals": "food", "orders": "orders", "bookings": "bookings", "reminders": "reminders"}
COLLECTIONS = ("guests", "wellness_days", "sessions", "session_events", "food_catalog", "guest_health_imports", *RECORDS)


def initial_state(date, profile=None):
    return {
        "profile": {**deepcopy(PROFILE), **(profile or {})}, "date": date, "clock": None,
        "food": [], "orders": {}, "bookings": {}, "reminders": {}, "sessions": {},
    }


def initialize_mongo(database):
    from pymongo.errors import CollectionInvalid

    existing = set(database.list_collection_names())
    for name in COLLECTIONS:
        if name not in existing:
            try:
                database.create_collection(name)
            except CollectionInvalid:
                pass  # Another initializer created it.
    database.wellness_days.create_index([("dataset_id", 1), ("date", 1)], unique=True)
    database.sessions.create_index([("guest_id", 1), ("updated_at", -1)])
    database.session_events.create_index([("guest_id", 1), ("session_id", 1), ("seq", 1)], unique=True)
    database.meals.create_index([("guest_id", 1), ("date", 1)])
    for name in ("orders", "bookings", "reminders"):
        database[name].create_index("guest_id")
    database.bookings.create_index("id")


def read_guest_recommendation_data(database, owner, day):
    """Read fresh recommendation inputs for one authenticated guest ID."""
    guest = database.guests.find_one({"_id": owner}, {"_id": 0, "profile": 1, "persona": 1})
    if guest is None:
        return None
    persona = guest.get("persona")
    if persona:
        for field, marker, prefix in (
            ("wearable_daily", "import_id", "initial-wellness-"),
            ("food_history_log", "log_id", "initial-meal-"),
        ):
            recorded, samples = [], []
            for row in persona.get(field, []):
                if str(row.get(marker, "")).startswith(prefix):
                    samples.append({**row, "source": "imported_sample"})
                else:
                    recorded.append(row)
            persona[field] = recorded or samples
    return {
        **guest,
        "meals": list(database.meals.find(
            {"guest_id": owner, "date": day, "id": {"$not": {"$regex": "^seed-"}}}, {"_id": 0, "guest_id": 0},
        )),
    }


def read_food_catalog(database):
    catalog = database.food_catalog.find_one({"_id": "food_db"}, {"_id": 0, "foods": 1})
    return catalog.get("foods", []) if catalog else []


def confirm_exercise(database, owner, workout):
    """Confirm once, retaining the surrounding MongoDB health history."""
    for _ in range(3):
        guest = database.guests.find_one({"_id": owner}, {"profile.name": 1, "persona": 1})
        if guest is None:
            raise LookupError("Guest profile not found.")
        previous = guest.get("persona")
        persona = deepcopy(previous) if previous else {
            "profile": {"persona_id": owner[:40], "display_name": guest["profile"]["name"]},
        }
        workouts = persona.setdefault("workouts", [])
        for index, entry in enumerate(workouts):
            day = history_date(entry)
            if entry.get("id") == workout["id"] or (
                day is not None and day.isoformat() == workout["date"] and
                str(entry.get("name", "")).casefold() == workout["name"].casefold() and
                str(entry.get("location", "")).strip().casefold() == workout["location"].strip().casefold()
            ):
                if entry.get("source") != "imported_sample":
                    return False
                workouts[index] = {**entry, **workout, "source": "user_confirmed"}
                break
        else:
            workouts.append({**workout, "source": "user_confirmed"})
        match = {"_id": owner, "persona": previous if "persona" in guest else {"$exists": False}}
        if database.guests.update_one(match, {"$set": {"persona": persona}}).matched_count:
            return True
    raise ValueError("Your health history changed during the review. Try again.")


class MongoStore:
    """Persist a visitor's game state using the existing single-worker save interface."""

    def __init__(self, database, owner, date, *, demo, profile=None):
        self.database, self.owner, self.demo = database, owner, demo
        self.state = initial_state(date, profile)
        self.saved = {}
        guest = database.guests.find_one({"_id": owner})
        if guest:
            self.state.update({key: guest[key] for key in ("profile", "date", "clock")})
            for key in ("persona", "push_subscriptions"):
                if guest.get(key):
                    self.state[key] = guest[key]
            self.load_records()
        if guest:
            self.saved = deepcopy(self.documents())
        if not demo and not self.state.get("persona"):
            name = self.state["profile"]["name"]
            template = database.guest_health_imports.find_one({"_id": name.strip().casefold()})
            if template:
                day = self.state["date"]
                self.state["persona"] = {
                    "profile": {"persona_id": owner[:40], "display_name": name},
                    "wearable_daily": [{**row, "date": day} for row in template["wearable_daily"]],
                    "food_history_log": [{**row, "date": day, "timestamp": day + row["timestamp"][10:]}
                                         for row in template["food_history_log"]],
                }
                self.save()
                return
        if not guest:
            self.save()

    def load_records(self):
        for name, key in RECORDS.items():
            rows = list(self.database[name].find({"guest_id": self.owner}, {"_id": 0, "guest_id": 0}))
            self.state[key] = sorted(rows, key=lambda row: row["time"]) if key == "food" else {
                row.get("id") or row["order_id"]: row for row in rows
            }
        for raw in self.database.sessions.find({"guest_id": self.owner}, {"_id": 0, "guest_id": 0}):
            session_id = raw.pop("id")
            raw.update(feed=[], history=[], timeline=[])
            self.state["sessions"][session_id] = raw
        events = self.database.session_events.find(
            {"guest_id": self.owner}, {"_id": 0, "guest_id": 0},
        ).sort("seq")
        for raw in events:
            session = self.state["sessions"].get(raw.pop("session_id"))
            if session is None:
                continue
            session["timeline"].append(raw)
            if raw["type"] == "feed":
                session["feed"].append(raw["item"])
            elif raw["type"] == "turn":
                session["history"].extend([
                    {"role": "user", "content": raw["message"]},
                    {"role": "assistant", "content": "".join(
                        item["text"] for item in raw["events"] if item["type"] == "delta"
                    )},
                ])

    def documents(self):
        state = self.state
        docs = {name: {} for name in ("guests", "sessions", "session_events", *RECORDS)}
        docs["guests"][self.owner] = {
            **{key: state[key] for key in ("profile", "date", "clock")},
            **{key: state[key] for key in ("persona", "push_subscriptions") if state.get(key)},
            "dataset_id": DATASET, "demo": self.demo,
        }
        for name, key in RECORDS.items():
            rows = state[key] if key == "food" else state[key].values()
            for row in rows:
                record_id = row.get("id") or row["order_id"]
                docs[name][f"{self.owner}:{record_id}"] = {"guest_id": self.owner, **row}
        for session_id, session in state["sessions"].items():
            prefix = f"{self.owner}:{session_id}"
            docs["sessions"][prefix] = {"guest_id": self.owner, "id": session_id, **{
                key: value for key, value in session.items() if key not in {"feed", "history", "timeline"}
            }}
            for event in session.get("timeline", []):
                docs["session_events"][f"{prefix}:{event['seq']}"] = {
                    "guest_id": self.owner, "session_id": session_id, **event,
                }
        return docs

    def save(self):
        documents = self.documents()
        for name, rows in documents.items():
            previous = self.saved.get(name, {})
            collection = self.database[name]
            for key, value in rows.items():
                if previous.get(key) != value:
                    old = previous.get(key)
                    if name == "guests" and old is not None:
                        changed = {field: item for field, item in value.items() if old.get(field) != item}
                        removed_fields = {field: "" for field in old.keys() - value.keys()}
                        updates = {}
                        if changed:
                            updates["$set"] = changed
                        if removed_fields:
                            updates["$unset"] = removed_fields
                        collection.update_one({"_id": key}, updates)
                    else:
                        collection.replace_one({"_id": key}, {"_id": key, **value}, upsert=True)
            removed = list(previous.keys() - rows.keys())
            if removed:
                collection.delete_many({"_id": {"$in": removed}})
        self.saved = deepcopy(documents)

    def reset(self, date):
        previous = self.state
        self.state = initial_state(date, previous["profile"])
        if "persona" in previous:
            self.state["persona"] = previous["persona"]
        self.state["food"] = previous["food"]
        try:
            self.save()
        except Exception:
            self.state = previous
            raise


class VisitorStores:
    def __init__(self, date, database):
        self.date, self.database = date, database

    def open(self, owner, *, demo, profile=None, create=False):
        if not create and not self.database.guests.find_one({"_id": owner}, {"_id": 1}):
            return None
        return MongoStore(self.database, owner, self.date, demo=demo, profile=profile)

    def find_owners(self, name):
        """Guest owners whose profile name matches, case-insensitively."""
        import re

        pattern = {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}
        return [doc["_id"] for doc in self.database.guests.find({"profile.name": pattern}, {"_id": 1})]

    def booking_owner(self, booking_id):
        doc = self.database.bookings.find_one({"id": booking_id}, {"guest_id": 1})
        return doc["guest_id"] if doc else None


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pymongo import MongoClient

    load_dotenv()
    with MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000) as client:
        database = client[os.getenv("MONGO_DATABASE") or "zippy"]
        initialize_mongo(database)
        print(f"Initialized {database.name}: {', '.join(COLLECTIONS)}")
