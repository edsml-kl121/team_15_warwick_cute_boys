import json
from contextlib import contextmanager

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from main import Settings, create_app


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
        assert image == b"photo"
        assert key.startswith("meals/") and key.endswith(".jpg")
        return {"dish": "Rice and chicken", "kcal": 350, "protein_g": 28, "carbs_g": 32, "fat_g": 12}

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
