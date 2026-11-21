import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from demo import Clock, DEMO_DATE, seed


DATASET = "ploy-v1"
RECORDS = {"meals": "food", "orders": "orders", "bookings": "bookings", "reminders": "reminders"}
COLLECTIONS = ("guests", "wellness_days", "sessions", "session_events", *RECORDS)


def initial_state(date, demo, profile=None):
    state = seed(date)
    if not demo:
        state["profile"].update(profile or {})
        state["food"] = []
    return state


class JsonStore:
    def __init__(self, directory, date, *, demo=True, profile=None):
        self.path = Path(directory) / "demo.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.demo = demo
        self.state = json.loads(self.path.read_text()) if self.path.exists() else initial_state(date, demo, profile)

    def save(self):
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary:
            try:
                json.dump(self.state, temporary, ensure_ascii=False)
                temporary.flush()
                os.fsync(temporary.fileno())
                os.replace(temporary.name, self.path)
            finally:
                Path(temporary.name).unlink(missing_ok=True)

    def reset(self, date):
        previous = self.state
        self.state = seed(date)
        try:
            self.save()
        except Exception:
            self.state = previous
            raise


def initialize_mongo(database, date):
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
    database.wellness_days.update_one(
        {"dataset_id": DATASET, "date": date},
        {"$setOnInsert": seed(date)["day_data"][date]}, upsert=True,
    )


class MongoStore:
    """Persist a visitor's game state using the existing single-worker save interface."""

    def __init__(self, database, owner, date, *, demo, profile=None):
        self.database, self.owner, self.demo = database, owner, demo
        self.state = initial_state(date, demo, profile)
        self.saved = {}
        guest = database.guests.find_one({"_id": owner})
        if guest:
            self.state.update({key: guest[key] for key in ("profile", "date", "clock")})
            self.load_records()
        source_day = database.wellness_days.find_one(
            {"dataset_id": DATASET, "date": self.state["date"]}, {"_id": 0, "dataset_id": 0, "date": 0},
        )
        if source_day is None:
            raise RuntimeError("The mock wellness day has not been seeded.")
        self.state["day_data"] = {self.state["date"]: source_day}
        if guest:
            self.saved = deepcopy(self.documents())
        else:
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
        docs = {name: {} for name in COLLECTIONS if name != "wellness_days"}
        docs["guests"][self.owner] = {
            **{key: state[key] for key in ("profile", "date", "clock")},
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
                    collection.replace_one({"_id": key}, {"_id": key, **value}, upsert=True)
            removed = list(previous.keys() - rows.keys())
            if removed:
                collection.delete_many({"_id": {"$in": removed}})
        self.saved = deepcopy(documents)

    def reset(self, date):
        previous = self.state
        self.state = seed(date)
        self.state["day_data"] = previous["day_data"]
        try:
            self.save()
        except Exception:
            self.state = previous
            raise


class VisitorStores:
    def __init__(self, directory, date, database=None):
        self.directory, self.date, self.database = Path(directory), date, database

    def open(self, owner, *, demo, profile=None, create=False):
        if self.database is not None:
            if not create and not self.database.guests.find_one({"_id": owner}, {"_id": 1}):
                return None
            return MongoStore(self.database, owner, self.date, demo=demo, profile=profile)
        directory = self.directory / "visitors" / owner
        if not create and not (directory / "demo.json").exists():
            return None
        store = JsonStore(directory, self.date, demo=demo, profile=profile)
        if create:
            store.save()
        return store

    def booking_owner(self, booking_id):
        if self.database is not None:
            doc = self.database.bookings.find_one({"id": booking_id}, {"guest_id": 1})
            return doc["guest_id"] if doc else None
        for path in (self.directory / "visitors").glob("*/demo.json"):
            if booking_id in json.loads(path.read_text())["bookings"]:
                return path.parent.name
        return None


class DemoHealth:
    def today(self, state, date):
        return state["day_data"].get(date, state["day_data"][state["date"]])


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pymongo import MongoClient

    load_dotenv()
    clock = Clock(os.getenv("DEMO_NOW", f"{DEMO_DATE}T07:02:00+07:00"))
    with MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000) as client:
        database = client[os.getenv("MONGO_DATABASE") or "zippy"]
        initialize_mongo(database, clock.now().date().isoformat())
        print(f"Initialized {database.name}: {', '.join(COLLECTIONS)}")
