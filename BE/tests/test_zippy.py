import json
from contextlib import contextmanager

import mongomock
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from main import Settings, create_app
from storage import COLLECTIONS


class FakeShopee:
    def __init__(self):
        self.status = "pending_payment"
        self.calls = []

    async def call(self, name, **values):
        self.calls.append((name, values))
        if name == "search_products":
            return [{"product_id": "p_eyemask", "name": "3D Contoured Sleep Eye Mask", "shop": "Dreamy Sleep Official",
                     "price_thb": 199, "rating": 4.8, "description": "Blocks all light"}]
        if name == "place_mall_order":
            assert values == {"items": [{"product_id": "p_eyemask", "qty": 1}]}
            self.status = "pending_payment"
            return {"id": "order-1", "shipping_thb": 30, "total_thb": 229, "eta_days": 1}
        if name == "request_payment":
            return {"approve_url": "https://sim.example/pay/demo"}
        if name == "get_order_status":
            return {"status": self.status}
        if name == "cancel_order":
            self.status = "cancelled"
            return {"status": self.status}
        if name == "find_similar_dishes":
            assert values["calories"] == 400
            return [{"shop_id": shop_id, "name": "Caesar chicken", "price_thb": price,
                     "nutrition": {"protein_g": protein},
                     "restaurant": {"shop_id": shop_id, "name": title, "distance_km": distance}}
                    for shop_id, title, price, protein, distance in [
                        ("s_easy_health", "Easy Health", 265, 45, 1.25),
                        ("s_salad_factory", "Salad Factory", 245, 35, .83),
                        ("s_other", "Other", 275, 34, 1.6),
                    ]]
        if name == "get_menu":
            return {"name": {"s_easy_health": "Easy Health", "s_salad_factory": "Salad Factory"}[values["shop_id"]],
                    "phone": "+10000000000", "address": "Silom, Bangkok"}
        raise AssertionError(name)


class FakePhone:
    def validate(self, number):
        assert number == "+10000000000"

    async def start(self, service, booking):
        if booking["shop_id"] == "s_easy_health":
            await service.finish_call(booking["id"], "no_answer", 40)
        else:
            service.call_connected(booking["id"])
            booking["quote"] = "Yes, 7pm for one."
            await service.finish_call(booking["id"], "booked", 34)


class FakePhotos:
    async def read(self, image, key):
        assert key.startswith("meals/") and key.endswith(".jpg")
        if image == b"not food":
            raise ValueError("No food was clearly visible.")
        assert image == b"photo"
        return {"dish": "Rice and chicken", "kcal": 350, "protein_g": 28, "carbs_g": 32, "fat_g": 12,
                "items": [{"name": "Rice and chicken", "portion": "1 bowl", "kcal": 350}],
                "uncertainty": "The bowl size is estimated."}

    def url(self, key):
        return f"https://example.test/{key}"


@contextmanager
def demo(tmp_path, **options):
    settings = Settings()
    settings.token = "test-token"
    settings.directory = tmp_path
    settings.use_ai = False
    settings.mongo_url = None
    settings.secure_cookies = False
    fake = FakeShopee()
    options.setdefault("database", mongomock.MongoClient().zippy)
    app = create_app(settings=settings, shopee=fake, phone=FakePhone(), photos=FakePhotos(), **options)
    with TestClient(app, headers={"Authorization": "Bearer test-token", "X-Zippy-Demo": "1"}) as client:
        assert client.get("/today").status_code == 401
        assert client.post("/visitor").json() == {"ready": True}
        yield client, fake


def say(client, message):
    response = client.post("/chat", json={"message": message})
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.iter_lines()]
    assert events[-1]["type"] == "done", events
    return events


def cards(items):
    return [item["card"] for item in items if "card" in item]


def test_sleep_and_checkout(tmp_path):
    with demo(tmp_path) as (client, simulator):
        assert client.post("/demo/trigger", json={"moment": "morning_sleep"}).is_success
        feed = client.get("/feed").json()
        assert feed[0]["notify"]["title"] == "Sleep insight"
        assert cards(feed)[0]["deep_minutes"] == 58
        assert client.post("/demo/trigger", json={"moment": "morning_sleep"}).is_success
        assert client.get(f"/feed?after={feed[-1]['id']}").json() == []
        assert cards(say(client, "How did I sleep?"))[0]["deep_minutes"] == 58
        assert cards(say(client, "Show me options"))[0]["products"][0]["price_thb"] == 199
        order = client.post("/actions/buy", json={"item_id": "p_eyemask"}).json()
        assert order["total_thb"] == 229
        assert order["arrival_date"] == "2026-11-22"
        pay = client.post("/actions/pay", json={"order_id": order["order_id"]})
        assert pay.json()["approve_url"] == "https://sim.example/pay/demo"
        assert client.get("/shopee-orders/order-1").json() == {"status": "unpaid"}
        simulator.status = "confirmed"
        for _ in range(2):
            assert client.get("/shopee-orders/order-1").json() == {"status": "paid"}
        kinds = [card["kind"] for card in cards(client.get("/feed").json())]
        assert kinds.count("payment_status") == 1
        assert kinds.count("reminder") == 1


def test_dinner_then_retry_and_walk(tmp_path):
    with demo(tmp_path) as (client, simulator):
        assert client.post("/demo/trigger", json={"moment": "dinner_tip"}).is_success
        dinner = cards(client.get("/feed").json())
        assert [card["kind"] for card in dinner] == ["meal", "places", "activity"]
        assert dinner[1]["places"][0]["protein_g"] == 45
        say(client, "Yes, I'll walk")
        assert not any(name == "get_menu" for name, _ in simulator.calls)
        say(client, "Yes, book it")
        assert next(card for card in cards(client.get("/feed").json()) if card["kind"] == "call")["status"] == "no_answer"
        say(client, "Call Salad Factory")
        results = cards(client.get("/feed").json())
        assert any(card.get("quote") == "Yes, 7pm for one." and card["duration_s"] == 34 for card in results)
        assert any(card["kind"] == "walk_route" and card["leave_by"] == "18:48" for card in results)
        assert client.post("/demo/trigger", json={"reminder": "18:48"}).is_success
        assert client.get("/feed").json()[-1]["notify"]["title"] == "Time to go"
        assert client.post("/demo/trigger", json={"moment": "daily_summary"}).is_success
        assert cards(client.get("/feed").json())[-1]["kind"] == "daily_summary"


def test_photo_reset_and_access_checks(tmp_path):
    with demo(tmp_path) as (client, simulator):
        assert client.get("/today", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.post("/call-status?booking_id=abc").status_code == 403
        try:
            with client.websocket_connect("/media-stream"):
                raise AssertionError("A request without a signature was accepted.")
        except WebSocketDisconnect as error:
            assert error.code == 1008
        photo = client.post("/food-log/photo", files={"file": ("meal.jpg", b"photo", "image/jpeg")})
        assert photo.is_success
        assert photo.json()["source"] == "photo"
        assert photo.json()["photo_url"].startswith("https://example.test/meals/")
        assert client.get("/food-log").json()["totals"]["protein_g"] == 78
        say(client, "Show me options")
        assert client.post("/actions/buy", json={"item_id": "p_eyemask"}).is_success
        assert client.post("/demo/reset").is_success
        assert simulator.status == "cancelled"
        assert client.get("/food-log").json()["totals"]["protein_g"] == 50
        assert client.get("/feed").json() == []


def test_guest_data_and_cards_survive_backend_restart(tmp_path):
    database = mongomock.MongoClient().zippy
    guest_headers = {"X-Zippy-Demo": "0"}
    with demo(tmp_path, database=database) as (client, _):
        assert client.get("/visitor", headers=guest_headers).json() == {"ready": False}
        assert client.get("/profile", headers=guest_headers).status_code == 401
        reply = client.post("/visitor", headers=guest_headers, json={
            "name": "  Nok ", "food": "Vegetarian", "budget_thb": 200,
        })
        assert reply.is_success
        assert "httponly" in reply.headers["set-cookie"].lower()
        guest_token = client.cookies["zippy_guest"]
        assert client.get("/profile", headers=guest_headers).json()["name"] == "Nok"
        assert client.get("/profile").json()["name"] == "Ploy"
        assert client.get("/today", headers=guest_headers).json()["demo_data"] is True
        assert client.post("/demo/reset", headers=guest_headers).status_code == 403
        chat = client.post("/chat", headers=guest_headers, json={"session_id": "guest-chat", "message": "How did I sleep?"})
        assert json.loads(chat.text.splitlines()[-1]) == {"type": "done"}
        image = client.post("/food-log/photo?session_id=guest-chat", headers=guest_headers,
                            files={"file": ("meal.jpg", b"photo", "image/jpeg")})
        assert image.is_success
        photo_url = image.json()["photo_url"]
        image_doc = database.meals.find_one({"id": image.json()["id"]})
        assert image_doc["photo_key"].startswith("meals/")
        assert "photo_url" not in image_doc
        assert client.get("/sessions/guest-chat").status_code == 404
        assert client.post("/demo/reset").is_success
        assert client.delete("/visitor", headers=guest_headers).json() == {"ready": False}
        assert client.get("/visitor", headers=guest_headers).json() == {"ready": False}
        assert client.get("/profile", headers=guest_headers).status_code == 401
        assert client.get("/profile").json()["name"] == "Ploy"
        assert client.post("/visitor", headers=guest_headers, json={"name": "Pim"}).is_success
        assert client.get("/sessions", headers=guest_headers).json() == []
        assert client.get("/sessions/guest-chat", headers=guest_headers).status_code == 404
        assert client.get("/food-log", headers=guest_headers).json()["meals"] == []

    with demo(tmp_path, database=database) as (client, _):
        client.cookies.set("zippy_guest", guest_token)
        assert client.get("/visitor", headers=guest_headers).json() == {"ready": True}
        profile = client.get("/profile", headers=guest_headers).json()
        assert profile["name"] == "Nok"
        assert profile["preferences"]["budget_thb"] == 200
        history = client.get("/sessions/guest-chat", headers=guest_headers).json()
        assert history["last_feed_id"] == 1
        assert [event["type"] for event in history["timeline"]] == ["turn", "feed"]
        assert cards(history["timeline"][0]["events"])[0]["deep_minutes"] == 58
        assert client.get("/food-log", headers=guest_headers).json()["meals"][0]["photo_url"] == photo_url
        assert database.wellness_days.count_documents({}) == 1
        assert set(database.list_collection_names()) == set(COLLECTIONS)


PERSONA = {
    "as_of": "2026-12-20T23:59:00+07:00",
    "profile": {
        "persona_id": "P01", "display_name": "Krit", "age": 25, "daily_calorie_target": 2491,
        "macro_targets": {"carbs_g": 232, "fat_g": 56, "protein_g": 142},
        "cuisine_prefs": ["italian"], "favorite_dishes": ["Spaghetti Bolognese"],
        "home_area": {"district": "Ari", "city": "Bangkok"}, "connected_sources": ["fitbit", "whoop"],
        "summary_30d": {"avg_daily_intake": {"calories": 2681}},
    },
    "food_history_log": [
        {"log_id": "P01-1", "date": "2026-11-21", "timestamp": "2026-11-21T12:05:00+07:00", "meal_time": "lunch",
         "meal_name": "Thai Pork Spread", "channel": "shopee_food_order", "order": {"restaurant": "FitMeal BKK"},
         "items": [{"dish_name": "Steamed Jasmine Rice"}],
         "meal_totals": {"calories": 1082, "protein_g": 80.7, "carbs_g": 77.4, "fat_g": 46.3}},
        {"log_id": "P01-2", "date": "2026-11-22", "timestamp": "2026-11-22T09:59:00+07:00", "meal_time": "breakfast",
         "channel": "agent_call", "agent_call": {"logged_via": "photo"}, "items": [{"dish_name": "Omurice"}],
         "meal_totals": {"calories": 600, "protein_g": 22, "carbs_g": 83.6, "fat_g": 20.9}},
    ],
    "wearable_daily": [{"date": "2026-11-21", "steps": 2407}],
    "weights": [{"date": "2026-11-21", "weight_kg": 72.2}, {"date": "2026-12-18", "weight_kg": 71.3}],
}


def test_persona_upload_personalises_profile_food_log_and_coach_context(tmp_path):
    from persona import recommendation_context

    database = mongomock.MongoClient().zippy
    guest = {"X-Zippy-Demo": "0"}
    with demo(tmp_path, database=database) as (client, _):
        assert client.post("/visitor", headers=guest, json={"name": "Guest"}).is_success
        assert client.get("/persona", headers=guest).status_code == 404
        assert client.put("/persona", headers=guest, json={"profile": {"display_name": "No id"}}).status_code == 422

        saved = client.put("/persona", headers=guest, json=PERSONA)
        assert saved.is_success and saved.json()["meals"] == 2
        profile = client.get("/profile", headers=guest).json()
        assert profile["name"] == "Krit" and profile["location"] == "Ari, Bangkok"
        assert profile["goals"]["kcal"] == 2491 and profile["goals"]["protein_g"] == 142
        assert {"Fitbit", "Whoop"} <= {item["app"] for item in profile["connections"]}

        meals = client.get("/food-log?date=2026-11-21", headers=guest).json()
        assert [(meal["dish"], meal["source"], meal["place"]) for meal in meals["meals"]] == [
            ("Thai Pork Spread", "shopee_food", "FitMeal BKK")]
        assert meals["totals"]["kcal"] == 1082
        assert client.get("/food-log?date=2026-11-22", headers=guest).json()["meals"][0]["source"] == "photo"
        assert client.get("/persona").status_code == 404  # the Ploy demo visitor stays separate

    stored = database.guests.find_one({"persona.profile.persona_id": "P01"})
    assert stored is not None
    context = recommendation_context(stored["persona"])
    assert context["top_restaurants"] == ["FitMeal BKK"]
    assert context["weight_trend"]["last"]["weight_kg"] == 71.3
    assert recommendation_context(None) == {"available": False}


def test_photo_stream_reports_progress_and_logs_only_success(tmp_path):
    with demo(tmp_path) as (client, _):
        scan = "/food-log/photo?stream=true"
        failed = client.post(scan, files={"file": ("not-food.jpg", b"not food", "image/jpeg")})
        assert [json.loads(line)["type"] for line in failed.iter_lines()] == ["progress", "error"]
        assert client.get("/food-log").json()["totals"]["protein_g"] == 50
        response = client.post(scan, files={"file": ("meal.jpg", b"photo", "image/jpeg")})
        assert response.headers["content-type"].startswith("application/x-ndjson")
        analyzing, saving, done = map(json.loads, response.iter_lines())
        assert analyzing == {"type": "progress", "stage": "analyzing"}
        assert saving == {"type": "progress", "stage": "saving"}
        assert done["type"] == "done"
        assert done["meal"]["items"][0]["portion"] == "1 bowl"
        food_log = client.get("/food-log").json()
        assert food_log["totals"]["protein_g"] == 78
        assert food_log["meals"][-1]["id"] == done["meal"]["id"]
        assert "350 kcal" in client.get("/feed").json()[-1]["text"]
