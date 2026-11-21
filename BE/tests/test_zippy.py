import asyncio
import base64
import io
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace

import mongomock
from agents.tool_context import ToolContext
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from demo import Clock
from integrations import AgentsCoach
from main import Settings, create_app
from recommendations import BucketRecommendationData
from storage import COLLECTIONS
from telephony import TwilioPhone

TWILIO_TOKEN = "twilio-test-token"
PUBLIC_URL = "https://calls.example.test"


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
            self.dish_searches = [*getattr(self, "dish_searches", []), values]
            return [{"shop_id": shop_id, "name": "Caesar chicken", "price_thb": price,
                     "nutrition": {"protein_g": protein},
                     "restaurant": {"shop_id": shop_id, "name": title, "distance_km": distance,
                                    "image_url": f"https://sim.example/{shop_id}.jpg"}}
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


class FakeTwilioClient:
    """Stands in for twilio.rest.Client: records requests instead of dialing."""

    def __init__(self):
        self.created, self.hung_up = [], []
        client = self

        class Calls:
            def create(self, **request):
                client.created.append(request)
                return SimpleNamespace(sid="CA-test")

            def __call__(self, sid):
                return SimpleNamespace(update=lambda **change: client.hung_up.append((sid, change)))

        self.calls = Calls()


class FakeRealtime:
    """Stands in for RealtimeFactory: every prepared phone agent already has its greeting audio ready."""

    def __init__(self):
        self.prepared, self.closed = [], []

    async def prepare(self, booking):
        self.prepared.append(booking["id"])
        return FakePreparedCall(self, booking["id"])


class FakePreparedCall:
    def __init__(self, factory, booking_id):
        self.factory, self.booking_id = factory, booking_id
        self.end_requested = asyncio.Event()
        self.tracker = SimpleNamespace(on_play_bytes=lambda *played: None)
        self.session = self

    async def send_audio(self, data):
        pass

    async def __aiter__(self):
        yield SimpleNamespace(type="audio", audio=SimpleNamespace(data=b"greeting"), item_id="item-1", content_index=0)
        await asyncio.Event().wait()

    async def close(self):
        self.factory.closed.append(self.booking_id)


def twilio_phone(**options):
    phone = TwilioPhone("AC-test", TWILIO_TOKEN, "+19999999999", PUBLIC_URL, {"+10000000000"}, 40, 300, **options)
    phone.client = FakeTwilioClient()
    return phone


def twilio_post(client, phone, path, **fields):
    signature = RequestValidator(TWILIO_TOKEN).compute_signature(phone.public_url + path, fields)
    return client.post(path, data=fields, headers={"X-Twilio-Signature": signature})


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
def demo(tmp_path, pinned=True, **options):
    settings = Settings()
    settings.origin = "https://zippy.example"
    if pinned:
        settings.demo_now = "2026-11-21T07:02:00+07:00"
    settings.token = "test-token"
    settings.presenter_key = "local-presenter"
    settings.directory = tmp_path
    settings.use_ai = False
    settings.mongo_url = None
    settings.recommendation_mongo_url = None
    settings.secure_cookies = False
    fake = FakeShopee()
    options.setdefault("database", mongomock.MongoClient().zippy)
    phone = options.pop("phone", None) or FakePhone()
    app = create_app(settings=settings, shopee=fake, phone=phone, photos=FakePhotos(), **options)
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


def visitor(client):
    """The Ploy demo visitor's own Zippy, which the client's HTTP requests use."""
    token = client.cookies.get("zippy_ploy")
    return client.app.state.open_visitor("demo-" + sha256(token.encode()).hexdigest(), demo=True)


def coach_tools(client, session_id="ploy"):
    zippy = visitor(client)
    shown = asyncio.Queue()
    return {tool.name: tool for tool in AgentsCoach(zippy.prompts).tools(zippy, session_id, shown)}, shown


def use_tool(client, tools, name, **arguments):
    """Invoke a coach tool the way the Agents SDK does when the model calls it."""
    payload = json.dumps(arguments)
    context = ToolContext(context=None, tool_name=name, tool_call_id="call-1", tool_arguments=payload)
    result = client.portal.call(tools[name].on_invoke_tool, context, payload)
    client.portal.call(asyncio.sleep, 0.1)  # let the spawned call task finish
    return result


def test_sleep_trigger_can_be_replayed_from_the_presenter(tmp_path):
    with demo(tmp_path) as (client, simulator):
        assert client.post("/demo/trigger", json={"moment": "morning_sleep"}).is_success
        feed = client.get("/feed").json()
        assert feed[0]["notify"]["title"] == "Sleep insight"
        assert cards(feed)[0]["deep_minutes"] == 58
        assert client.post("/demo/trigger", json={"moment": "morning_sleep"}).is_success
        replay = client.get(f"/feed?after={feed[-1]['id']}").json()
        assert replay[0]["notify"]["title"] == "Sleep insight"
        assert cards(replay)[0]["deep_minutes"] == 58
        assert cards(say(client, "How did I sleep?"))[0]["deep_minutes"] == 58
        assert cards(say(client, "Show me options"))[0]["products"][0]["price_thb"] == 199
        order = client.post("/actions/buy", json={"item_id": "p_eyemask"}).json()
        assert order["total_thb"] == 229
        assert order["arrival_date"] == "2026-11-22"
        pay = client.post("/actions/pay", json={"order_id": order["order_id"]})
        assert pay.json()["approve_url"] == "https://sim.example/pay/demo"
        assert simulator.calls[-1] == ("request_payment", {
            "order_id": order["order_id"], "return_url": "https://zippy.example/?demo=ploy",
        })
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


def test_coach_finds_places_then_books_requested_time_and_party(tmp_path):
    with demo(tmp_path) as (client, _):
        tools, shown = coach_tools(client)
        use_tool(client, tools, "find_similar_dishes", dish="grilled chicken")
        places = shown.get_nowait()
        assert places["kind"] == "places"
        assert [place["name"] for place in places["places"]] == ["Easy Health", "Salad Factory", "Other"]
        use_tool(client, tools, "book_table_by_phone", shop_id="s_salad_factory", time="19:30", party_size=2,
                 request="a table for 2 at 7:30 pm, by the window if possible")
        booking = next(iter(visitor(client).state["bookings"].values()))
        assert (booking["restaurant_name"], booking["time"], booking["party_size"]) == ("Salad Factory", "19:30", 2)
        assert booking["request"] == "a table for 2 at 7:30 pm, by the window if possible"
        assert booking["status"] == "booked"
        route = next(card for card in cards(client.get("/feed").json()) if card["kind"] == "walk_route")
        assert route["leave_by"] == "19:18"


def test_coach_tells_model_which_places_it_can_book_on_later_turns(tmp_path):
    with demo(tmp_path) as (client, _):
        tools, _ = coach_tools(client)
        use_tool(client, tools, "find_similar_dishes", dish="grilled chicken")
        zippy = visitor(client)
        history = [{"role": "user", "content": "Find a salad"}, {"role": "assistant", "content": "Easy Health is closest."}]
        turn = AgentsCoach(zippy.prompts).input(zippy, "ploy", "Book the first one", history)
        assert turn[:2] == history
        assert all(shop_id in json.dumps(turn[2:-1]) for shop_id in ("s_easy_health", "s_salad_factory", "s_other"))
        assert turn[-1] == {"role": "user", "content": "Book the first one"}


def test_coach_reminds_model_to_reply_in_english_right_before_each_message(tmp_path):
    with demo(tmp_path) as (client, _):
        zippy = visitor(client)
        turn = AgentsCoach(zippy.prompts).input(zippy, "ploy", "เมื่อคืนนอนเป็นยังไง", [])
        assert turn[-1] == {"role": "user", "content": "เมื่อคืนนอนเป็นยังไง"}
        assert turn[-2]["role"] == "developer" and "English" in turn[-2]["content"]


def test_clock_follows_real_bangkok_time_when_not_pinned(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_NOW", raising=False)
    with demo(tmp_path, pinned=False) as (client, _):
        now = datetime.fromisoformat(client.get("/today").json()["now"])
        assert abs(now - datetime.now(timezone.utc)) < timedelta(minutes=1)
        assert now.utcoffset() == timedelta(hours=7)


def test_coach_is_told_the_current_time_every_turn(tmp_path):
    with demo(tmp_path) as (client, _):
        zippy = visitor(client)
        turn = AgentsCoach(zippy.prompts).input(zippy, "ploy", "Book a table in 30 minutes", [])
        assert "2026-11-21 07:02" in json.dumps([item for item in turn if item["role"] == "developer"])


def test_booking_a_time_that_already_passed_today_is_refused(tmp_path):
    with demo(tmp_path, clock=Clock("2026-11-21T19:45:00+07:00")) as (client, _):
        tools, _ = coach_tools(client)
        use_tool(client, tools, "find_similar_dishes", dish="grilled chicken")
        use_tool(client, tools, "book_table_by_phone", shop_id="s_salad_factory", time="19:30", party_size=2,
                 request="a table for 2 at 7:30 pm")
        assert visitor(client).state["bookings"] == {}
        use_tool(client, tools, "book_table_by_phone", shop_id="s_salad_factory", time="20:15", party_size=2,
                 request="a table for 2 at 8:15 pm")
        assert [booking["time"] for booking in visitor(client).state["bookings"].values()] == ["20:15"]


def test_coach_shows_products_as_cards_the_visitor_can_buy(tmp_path):
    with demo(tmp_path) as (client, simulator):
        tools, shown = coach_tools(client)
        use_tool(client, tools, "show_products", query="eye mask")
        assert ("search_products", {"query": "eye mask"}) in simulator.calls
        card = shown.get_nowait()
        assert card["kind"] == "product_compare"
        assert [product["item_id"] for product in card["products"]] == ["p_eyemask"]
        assert client.post("/actions/buy", json={"item_id": "p_eyemask"}).json()["total_thb"] == 229


def test_coach_dish_search_can_target_protein_and_calories(tmp_path):
    with demo(tmp_path) as (client, simulator):
        tools, _ = coach_tools(client)
        use_tool(client, tools, "find_similar_dishes", dish="high-protein snack", protein_g=30, calories=250)
        search = simulator.dish_searches[-1]
        assert (search["dish"], search["protein_g"], search["calories"]) == ("high-protein snack", 30, 250)


def test_coach_refuses_unlisted_restaurant_or_bad_booking_details(tmp_path):
    with demo(tmp_path) as (client, simulator):
        tools, _ = coach_tools(client)
        use_tool(client, tools, "book_table_by_phone", shop_id="s_made_up", time="19:00", party_size=1)
        use_tool(client, tools, "find_similar_dishes", dish="grilled chicken")
        use_tool(client, tools, "book_table_by_phone", shop_id="s_salad_factory", time="7pm", party_size=1)
        use_tool(client, tools, "book_table_by_phone", shop_id="s_salad_factory", time="19:00", party_size=0)
        assert visitor(client).state["bookings"] == {}
        assert not any(name == "get_menu" for name, _ in simulator.calls)


def book_dinner_call(client):
    assert client.post("/demo/trigger", json={"moment": "dinner_tip"}).is_success
    say(client, "Yes, I'll walk")
    say(client, "Yes, book it")
    client.portal.call(asyncio.sleep, 0.1)
    return next(iter(visitor(client).state["bookings"].values()))


def test_call_audio_starts_before_machine_detection_and_machines_are_hung_up(tmp_path):
    phone = twilio_phone()
    with demo(tmp_path, phone=phone) as (client, _):
        booking = book_dinner_call(client)
        request = phone.client.created[0]
        assert (request["machine_detection"], request["async_amd"]) == ("Enable", "true")
        assert request["async_amd_status_callback"] == f"{PUBLIC_URL}/call-amd?booking_id={booking['id']}"
        amd = twilio_post(client, phone, f"/call-amd?booking_id={booking['id']}", CallSid="CA-test", AnsweredBy="machine_start")
        assert amd.is_success
        assert phone.client.hung_up == [("CA-test", {"status": "completed"})]
        done = twilio_post(client, phone, f"/call-status?booking_id={booking['id']}",
                           CallSid="CA-test", CallStatus="completed", CallDuration="6")
        assert done.is_success
        assert next(card for card in cards(client.get("/feed").json()) if card["kind"] == "call")["status"] == "no_answer"


def test_human_answer_keeps_the_call_going(tmp_path):
    phone = twilio_phone()
    with demo(tmp_path, phone=phone) as (client, _):
        booking = book_dinner_call(client)
        amd = twilio_post(client, phone, f"/call-amd?booking_id={booking['id']}", CallSid="CA-test", AnsweredBy="human")
        assert amd.is_success
        assert phone.client.hung_up == []
        assert visitor(client).state["bookings"][booking["id"]]["status"] == "calling"


def test_phone_agent_is_ready_while_ringing_and_greets_as_soon_as_answered(tmp_path):
    realtime = FakeRealtime()
    phone = twilio_phone(realtime=realtime)
    with demo(tmp_path, phone=phone, realtime=realtime) as (client, _):
        booking = book_dinner_call(client)
        assert realtime.prepared == [booking["id"]]
        assert booking["request"] == "a table for 1 at 19:00"
        signature =RequestValidator(TWILIO_TOKEN).compute_signature(phone.media_url, {})
        with client.websocket_connect("/media-stream", headers={"X-Twilio-Signature": signature}) as twilio:
            twilio.send_json({"event": "connected"})
            twilio.send_json({"event": "start", "start": {"streamSid": "MZ-test", "callSid": "CA-test", "customParameters": {
                "purpose": "book_table", "booking_id": booking["id"]}}})
            first = twilio.receive_json()
            assert first["event"] == "media" and base64.b64decode(first["media"]["payload"]) == b"greeting"
            twilio.send_json({"event": "stop"})
        client.portal.call(asyncio.sleep, 0.1)
        assert realtime.prepared == [booking["id"]]
        assert realtime.closed == [booking["id"]]


def test_prepared_phone_agent_is_closed_when_nobody_answers(tmp_path):
    realtime = FakeRealtime()
    phone = twilio_phone(realtime=realtime)
    with demo(tmp_path, phone=phone, realtime=realtime) as (client, _):
        booking = book_dinner_call(client)
        status = twilio_post(client, phone, f"/call-status?booking_id={booking['id']}", CallSid="CA-test", CallStatus="no-answer")
        assert status.is_success
        assert realtime.closed == [booking["id"]]


def test_phone_agent_opens_by_introducing_zippy_and_the_booking():
    from integrations import Prompts
    from telephony import RealtimeFactory

    sent = []

    class Session:
        model = SimpleNamespace(send_event=lambda event: asyncio.sleep(0, sent.append(event)))

        async def enter(self):
            return self

    async def open_session(*_):
        return Session()

    factory = RealtimeFactory(Prompts(None), "realtime-test", None, "English", ["en"])
    factory.open = open_session
    request = "a table for 2 at 7:30 pm, by the window if possible"
    asyncio.run(factory.prepare({"restaurant_name": "Salad Factory", "party_size": 2, "time": "19:30", "name": "Ploy",
                                 "request": request}))
    message = sent[0].message
    assert message["type"] == "response.create"
    greeting = message["other_data"]["response"]["instructions"]
    assert all(detail in greeting for detail in ("Zippy", "Salad Factory", "Ploy", request))


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
            "name": "  Nok ", "food": "Vegetarian",
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
        assert "budget_thb" not in profile["preferences"]
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


class FakePush:
    public_key = "test-public-key"

    def __init__(self):
        self.sent = []
        self.gone = set()

    async def send(self, subscriptions, notification):
        self.sent.append(([item["endpoint"] for item in subscriptions], notification))
        return set(self.gone)


def test_presenter_agents_use_guest_data_and_publish_search_results(tmp_path):
    profile = {
        "persona_id": "P01", "display_name": "Krit", "daily_calorie_target": 1900,
        "macro_targets": {"protein_g": 90}, "cuisine_prefs": ["Thai"], "favorite_dishes": [],
        "allergies": ["peanuts"], "home_area": {"lat": 13.73, "lng": 100.53},
    }
    objects = {
        "body_data/user_profiles.json": {"personas": [profile]},
        "personas/P01_krit.json": {"profile": profile},
        "body_data/body_health_wearable.json": {"daily": [
            {"persona_id": "P01", "date": "2026-11-20", "sleep_hours": 5.5},
            {"persona_id": "P02", "date": "2026-11-20", "sleep_hours": 15},
        ]},
        "body_data/food_history_log.json": {"entries": [
            {"persona_id": "P01", "date": "2026-11-21",
             "items": [{"catalog_food_id": "rice", "dish_name": "Rice"}],
             "meal_totals": {"calories": 1350, "protein_g": 55}},
            {"persona_id": "P02", "date": "2026-11-21", "meal_totals": {"calories": 9000}},
        ]},
        "body_data/food_db.json": {"foods": [
            {"food_id": "chicken", "menu": "Chicken salad", "role": "salad", "cuisine": "Thai",
             "image_url": "https://hackathon.t3.storageapi.dev/food_db/chicken%20salad.jpg",
             "allergens": [], "nutrition": {"calories": 400, "protein_g": 35}},
            {"food_id": "peanut", "menu": "Thai peanut salad", "role": "salad", "cuisine": "Thai",
             "image_url": "https://hackathon.t3.storageapi.dev/body_data/user_profiles.json",
             "allergens": ["peanut"], "nutrition": {"calories": 400, "protein_g": 45}},
        ]},
    }

    class Bucket:
        meta = SimpleNamespace(endpoint_url="https://t3.storageapi.dev")

        def generate_presigned_url(self, method, *, Params, ExpiresIn):
            assert method == "get_object"
            assert Params == {"Bucket": "hackathon", "Key": "food_db/chicken salad.jpg"}
            assert ExpiresIn == 900
            return "https://hackathon.t3.storageapi.dev/food_db/chicken%20salad.jpg?signature=test"

        def list_objects_v2(self, *, Bucket, Prefix, MaxKeys):
            assert Bucket == "hackathon"
            return {"Contents": [{"Key": key} for key in objects if key.startswith(Prefix)]}

        def get_object(self, *, Bucket, Key):
            assert Bucket == "hackathon"
            return {"Body": io.BytesIO(json.dumps(objects[Key]).encode())}

    data = BucketRecommendationData(Bucket(), "hackathon")
    guest = {"X-Zippy-Demo": "0"}
    presenter = {"X-Presenter-Key": "local-presenter"}
    with demo(tmp_path, recommendation_data=data) as (client, simulator):
        assert client.post("/visitor", headers=guest, json={"name": "Krit"}).is_success
        body = {"guest_name": "krit", "agent": "food"}
        assert client.post("/presenter/trigger", json=body).status_code == 403
        assert client.post("/presenter/trigger", json={**body, "moment": "dinner_tip"},
                           headers=presenter).status_code == 400
        result = client.post("/presenter/trigger", json=body, headers=presenter)
        assert result.is_success, result.text
        assert result.json()["session_id"] == "presenter"
        feed = "/feed?session_id=presenter"
        meal, places = cards(client.get(feed, headers=guest).json())
        assert meal["dish"] == "Chicken salad"
        assert meal["food_id"] == "chicken"
        assert "35 g left toward today’s protein goal" in meal["why"]
        image = client.get("/food-log/catalog-image?food_id=chicken", follow_redirects=False)
        assert image.status_code == 307 and image.headers["location"].endswith("?signature=test")
        assert client.get("/food-log/catalog-image", params={"dish": "Chicken salad"},
                          follow_redirects=False).headers["location"] == image.headers["location"]
        assert client.get("/food-log/catalog-image?food_id=peanut").status_code == 404
        assert client.get("/food-log/catalog-image?food_id=chicken",
                          headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert [p["price_thb"] for p in places["places"]] == [265, 245, 275]
        assert simulator.calls[-1] == ("find_similar_dishes", {
            "dish": "Chicken salad", "calories": 400, "protein_g": 35,
            "limit": 35, "lat": 13.73, "lng": 100.53,
        })
        assert not client.get(feed).json()

        result = client.post("/presenter/trigger", json={**body, "agent": "item"}, headers=presenter)
        assert result.is_success, result.text
        entries = client.get(feed, headers=guest).json()
        assert any("5.5 hours" in entry.get("text", "") and "below your 7-hour goal" in entry["text"]
                   for entry in entries)
        assert cards(entries)[-1]["products"][0]["item_id"] == "p_eyemask"
        assert simulator.calls[-1] == ("search_products", {"query": "eye mask"})
        assert client.post("/actions/buy", headers=guest,
                           json={"session_id": "presenter", "item_id": "p_eyemask"}).is_success


def test_presenter_reminder_triggers_for_all_guests_named_mew(tmp_path):
    database = mongomock.MongoClient().zippy
    guest = {"X-Zippy-Demo": "0"}
    with demo(tmp_path, database=database) as (client, _):
        recipients = []
        for index, name in enumerate(("Mew", "MEW", "Other")):
            assert client.post("/visitor", headers=guest, json={"name": name}).is_success
            token = client.cookies["zippy_guest"]
            owner = "guest-" + sha256(token.encode()).hexdigest()
            session = f"phone-{index}"
            scoped = client.app.state.open_visitor(owner, demo=False)
            scoped.remind(session, "22:30", "Wear your eye mask")
            scoped.store.save()
            recipients.append((token, session))
            assert client.delete("/visitor", headers=guest).is_success

        body = {"guest_name": "mew", "reminder": "22:30"}
        assert client.post("/presenter/trigger", json=body).status_code == 403
        result = client.post("/presenter/trigger", json=body, headers={"X-Presenter-Key": "local-presenter"})
        assert result.is_success, result.text
        assert result.json() == {"status": "ok", "guests": 2, "matched_guests": 2, "devices": 0}
        for index, (token, session) in enumerate(recipients):
            client.cookies.set("zippy_guest", token)
            feed = client.get(f"/feed?session_id={session}", headers=guest).json()
            assert [entry["text"] for entry in feed] == (["Wear your eye mask"] if index < 2 else [])
            client.cookies.delete("zippy_guest")


def test_presenter_agents_read_fresh_mongo_history_and_handle_new_guests(tmp_path):
    class Catalog:
        async def persona(self, guest_name, *, food):
            return None

        async def read(self, key):
            assert key == "body_data/food_db.json"
            return {"foods": [{"food_id": "chicken", "menu": "Chicken salad", "role": "salad",
                               "nutrition": {"calories": 400, "protein_g": 35}}]}

    database = mongomock.MongoClient().zippy
    guest = {"X-Zippy-Demo": "0"}
    presenter = {"X-Presenter-Key": "local-presenter"}
    with demo(tmp_path, database=database, recommendation_data=Catalog()) as (client, _):
        assert client.post("/visitor", headers=guest, json={"name": "Fresh"}).is_success
        for agent in ("food", "item"):
            result = client.post("/presenter/trigger", json={"guest_name": "Fresh", "agent": agent}, headers=presenter)
            assert result.is_success, result.text
        feed = "/feed?session_id=presenter"
        entries = client.get(feed, headers=guest).json()
        assert cards(entries)[0]["dish"] == "Chicken salad"
        assert any("general sleep accessory" in item.get("text", "") for item in entries)

        token = client.cookies["zippy_guest"]
        owner = "guest-" + sha256(token.encode()).hexdigest()
        database.guests.update_one({"_id": owner}, {"$set": {"persona": {
            "profile": {"persona_id": "P10", "display_name": "Fresh"},
            "wearable_daily": [{"date": "2026-11-20", "sleep_hours": 5.5}],
        }}})
        result = client.post("/presenter/trigger", json={"guest_name": "Fresh", "agent": "item"}, headers=presenter)
        assert result.is_success, result.text
        assert "5.5 hours" in client.get(feed, headers=guest).json()[-2]["text"]


def test_push_subscribe_and_presenter_trigger_by_guest_name(tmp_path):
    import time

    push = FakePush()
    guest = {"X-Zippy-Demo": "0"}
    device = {"endpoint": "https://push.example/device-1", "keys": {"p256dh": "key", "auth": "secret"}}
    with demo(tmp_path, push=push) as (client, _):
        assert client.post("/visitor", headers=guest, json={"name": "Kong"}).is_success
        assert client.get("/push/key", headers=guest).json() == {"public_key": "test-public-key"}
        assert client.post("/push/subscribe", headers=guest, json={"session_id": "phone", "subscription": device}).json() == {"devices": 1}
        assert client.post("/push/subscribe", headers=guest, json={"session_id": "phone", "subscription": device}).json() == {"devices": 1}
        bad = {**device, "endpoint": "http://insecure.example"}
        assert client.post("/push/subscribe", headers=guest, json={"subscription": bad}).status_code == 422

        body = {"guest_name": "kong", "moment": "dinner_tip"}
        assert client.post("/presenter/trigger", json=body).status_code == 403
        assert client.post("/presenter/trigger", json={**body, "guest_name": "Nobody"},
                           headers={"X-Presenter-Key": "local-presenter"}).status_code == 404
        fired = client.post("/presenter/trigger", json=body, headers={"X-Presenter-Key": "local-presenter"})
        assert fired.is_success and fired.json()["devices"] == 1
        for _ in range(50):
            if push.sent:
                break
            time.sleep(0.02)
        endpoints, notification = push.sent[0]
        assert endpoints == ["https://push.example/device-1"] and notification["title"] == "Dinner tip"

        push.gone = {"https://push.example/device-1"}
        assert client.post("/presenter/trigger", json={**body, "moment": "daily_summary"},
                           headers={"X-Presenter-Key": "local-presenter"}).is_success
        for _ in range(50):
            if client.post("/push/subscribe", headers=guest, json={"subscription": {
                    **device, "endpoint": "https://push.example/device-2"}}).json()["devices"] == 1:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("expired device was not removed")


def test_push_key_reports_missing_configuration(tmp_path):
    with demo(tmp_path) as (client, _):
        assert client.get("/push/key").status_code == 503


def _meal(log_id, date, meal_time, dish, kcal, protein, restaurant=None, cuisine="italian"):
    entry = {"log_id": log_id, "date": date, "timestamp": f"{date}T12:00:00+07:00", "meal_time": meal_time,
             "meal_name": dish, "items": [{"dish_name": dish, "cuisine": cuisine,
                                            "nutrition": {"calories": kcal, "protein_g": protein}}],
             "meal_totals": {"calories": kcal, "protein_g": protein, "sodium_mg": 1500}}
    if restaurant:
        entry.update(channel="shopee_food_order", order={"restaurant": restaurant, "total_thb": 300})
    else:
        entry.update(channel="agent_call", agent_call={"logged_via": "chat"})
    return entry


def test_presenter_recap_and_dinner_use_imported_history(tmp_path):
    history = {**PERSONA, "food_history_log": [
        _meal("a", "2026-11-19", "breakfast", "Scrambled Eggs", 380, 20),
        _meal("b", "2026-11-19", "dinner", "Spaghetti Bolognese", 600, 32, "Pasta Fresca"),
        _meal("c", "2026-11-20", "dinner", "Spaghetti Bolognese", 600, 32, "Pasta Fresca"),
        _meal("d", "2026-11-20", "lunch", "Grilled Chicken Rice", 520, 40, "FitMeal BKK", "thai"),
        _meal("e", "2026-11-21", "lunch", "Steak Frites", 1400, 60, "Sunday Steakhouse", "american"),
    ]}
    guest = {"X-Zippy-Demo": "0"}
    presenter = {"X-Presenter-Key": "local-presenter"}
    with demo(tmp_path) as (client, shopee):
        assert client.post("/visitor", headers=guest, json={"name": "Krit"}).is_success
        assert client.put("/persona", headers=guest, json=history).is_success

        assert client.post("/presenter/trigger", headers=presenter, json={"guest_name": "Krit", "moment": "dinner_tip"}).is_success
        feed = client.get("/feed?session_id=presenter", headers=guest).json()
        meal = next(card for card in cards(feed) if card["kind"] == "meal")
        assert meal["dish"] == "Spaghetti Bolognese" and "Pasta Fresca" in meal["why"]
        assert shopee.dish_searches[-1]["dish"] == "Spaghetti Bolognese" and shopee.dish_searches[-1]["calories"] == 600

        assert client.post("/presenter/trigger", headers=presenter, json={"guest_name": "Krit", "moment": "weekly_recap"}).is_success
        feed = client.get("/feed?session_id=presenter", headers=guest).json()
        recap = next(card for card in cards(feed) if card["kind"] == "weekly_recap")
        assert recap["days"] == 3 and recap["top_restaurant"] == "Pasta Fresca" and recap["kcal_goal"] == 2491
        assert feed[-1]["quick_replies"] == ["Plan tomorrow's meals", "Find lighter orders", "Not now"]
        assert feed[0]["notify"]["title"] in {"Dinner tip", "Your week"}

        plan = "".join(event.get("text", "") for event in say_as(client, guest, "Plan tomorrow's meals"))
        assert "| Breakfast | Scrambled Eggs |" in plan and "Spaghetti Bolognese" in plan
        lighter = "".join(event.get("text", "") for event in say_as(client, guest, "Find lighter orders"))
        assert lighter.splitlines()[2].startswith("- **Grilled Chicken Rice** at FitMeal BKK")


def say_as(client, headers, message):
    response = client.post("/chat", headers=headers, json={"session_id": "presenter", "message": message})
    events = [json.loads(line) for line in response.iter_lines()]
    assert events[-1]["type"] == "done", events
    return events


class FakeImages:
    async def find(self, folder, name):
        return f"https://bucket.example/{folder}/{name}.jpg" if (folder, name) in {
            ("dishes", "Grilled chicken salad"), ("restaurants", "s_easy_health")} else None


def test_dinner_cards_carry_bucket_and_restaurant_images(tmp_path):
    with demo(tmp_path, images=FakeImages()) as (client, _):
        assert client.post("/demo/trigger", json={"moment": "dinner_tip"}).is_success
        meal, places, _activity = cards(client.get("/feed").json())
        assert meal["image_url"] == "https://bucket.example/dishes/Grilled chicken salad.jpg"
        by_shop = {place["shop_id"]: place for place in places["places"]}
        assert by_shop["s_easy_health"]["image_url"] == "https://bucket.example/restaurants/s_easy_health.jpg"
        assert "image_url" not in by_shop["s_salad_factory"]
        assert by_shop["s_salad_factory"]["stock_image_url"] == "https://sim.example/s_salad_factory.jpg"


def test_bucket_images_find_slugged_keys_across_extensions():
    import asyncio

    from integrations import BucketImages, image_slug

    class Client:
        stored = {"dishes/spaghetti-bolognese.webp"}

        def head_object(self, Bucket, Key):
            if Key not in self.stored:
                raise LookupError(Key)

        def generate_presigned_url(self, _operation, Params, ExpiresIn):
            return f"https://signed.example/{Params['Key']}"

    images = BucketImages("menu", Client())
    assert image_slug("Spaghetti Bolognese (Large)") == "spaghetti-bolognese-large"
    assert asyncio.run(images.find("dishes", "Spaghetti  Bolognese")) == "https://signed.example/dishes/spaghetti-bolognese.webp"
    assert asyncio.run(images.find("restaurants", "s_missing")) is None
