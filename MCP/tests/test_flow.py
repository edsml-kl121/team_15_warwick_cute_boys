import pytest

from app.store import DEMO_PIN, START_BALANCE, SimError, Store


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def sim():
    clock = Clock()
    return Store(now=clock), clock


def test_food_order_happy_path(sim):
    s, clock = sim
    shop = s.search_restaurants("salmon")[0]
    item = s.get_menu(shop["shop_id"])["menu"][0]
    order = s.place_order("food", [{"item_id": item["item_id"], "qty": 2}])
    assert order["status"] == "pending_payment"
    assert order["nutrition_total"]["calories"] == item["nutrition"]["calories"] * 2

    intent = s.create_payment_intent(order["order_id"])
    s.approve_payment(intent["intent_id"], DEMO_PIN)
    assert s.wallet()["balance_thb"] == START_BALANCE - order["total_thb"]
    assert s.view_order(order["order_id"])["status"] == "confirmed"

    clock.t += 60
    assert s.view_order(order["order_id"])["status"] == "delivered"
    assert [o["order_id"] for o in s.take_newly_delivered()] == [order["order_id"]]
    assert s.take_newly_delivered() == []  # announced once


def test_wrong_pin_three_times_declines_and_charges_nothing(sim):
    s, _ = sim
    order = s.place_order("mall", [{"product_id": "p_eyemask"}])
    intent = s.create_payment_intent(order["order_id"])
    for _ in range(3):
        with pytest.raises(SimError) as err:
            s.approve_payment(intent["intent_id"], "000000")
        assert err.value.code == "wrong_pin"
    assert s.get_payment(intent["intent_id"])["status"] == "declined"
    with pytest.raises(SimError):
        s.approve_payment(intent["intent_id"], DEMO_PIN)
    assert s.wallet()["balance_thb"] == START_BALANCE


def test_insufficient_funds(sim):
    s, _ = sim
    order = s.place_order("food", [{"item_id": "m_massilia_2", "qty": 5}])
    intent = s.create_payment_intent(order["order_id"])
    with pytest.raises(SimError) as err:
        s.approve_payment(intent["intent_id"], DEMO_PIN)
    assert err.value.code == "insufficient_funds"
    assert s.view_order(order["order_id"])["status"] == "pending_payment"


def test_guards(sim):
    s, clock = sim
    with pytest.raises(SimError, match="multi_shop"):
        s.quote_food([{"item_id": "m_easy_health_1"}, {"item_id": "m_som_tam_1"}])
    with pytest.raises(SimError, match="item_not_found"):
        s.place_order("food", [{"item_id": "nope"}])
    order = s.place_order("food", [{"item_id": "m_som_tam_1"}])
    intent = s.create_payment_intent(order["order_id"])
    s.cancel_order(order["order_id"])
    with pytest.raises(SimError, match="not_pending"):
        s.approve_payment(intent["intent_id"], DEMO_PIN)
    order2 = s.place_order("food", [{"item_id": "m_som_tam_1"}])
    intent2 = s.create_payment_intent(order2["order_id"])
    clock.t += 601
    assert s.get_payment(intent2["intent_id"])["status"] == "expired"


def test_restaurants_expose_phone_for_booking_calls(sim):
    s, _ = sim
    shops = s.search_restaurants(max_km=50)
    assert shops and {shop["phone"] for shop in shops} == {"+16502013595"}  # demo line
    assert "phone" in s.get_menu(shops[0]["shop_id"])


def test_demo_phone_override_routes_every_call_to_one_number(monkeypatch):
    monkeypatch.setenv("SIM_DEMO_PHONE", "+66800000000")
    s = Store()
    assert {shop["phone"] for shop in s.search_restaurants(max_km=50)} == {"+66800000000"}


def test_find_similar_dishes_matches_recommended_dish_with_restaurant_info(sim):
    s, _ = sim
    hits = s.find_similar_dishes("grilled chicken breast salad")
    top = hits[0]
    assert {"chicken", "breast", "salad"} <= set(top["name"].lower().split())
    assert top["match_score"] >= hits[-1]["match_score"]
    assert {"phone", "address", "distance_km", "delivery_fee_thb"} <= set(top["restaurant"])


def test_find_similar_dishes_falls_back_to_macros_when_name_unknown(sim):
    s, _ = sim
    assert s.find_similar_dishes("quinoa tofu poke") == []
    hits = s.find_similar_dishes("quinoa tofu poke", calories=380, protein_g=32)
    assert hits[0]["nutrition"]["calories"] == 380
    assert hits[0]["nutrition"]["protein_g"] == 32


def test_eye_masks_come_from_several_shops_at_different_prices(sim):
    s, _ = sim
    masks = s.search_products("eye mask")
    assert len(masks) >= 4
    assert len({m["shop"] for m in masks}) >= 3
    assert len({m["price_thb"] for m in masks}) == len(masks)
    assert all(m["image_url"].endswith(f"/static/products/{m['product_id']}.jpg") for m in masks)


def test_mall_order_exposes_shipping_and_marks_payment_only_after_pin(sim):
    s, _ = sim
    order = s.place_order("mall", [{"product_id": "p_eyemask"}])
    assert (order["shipping_thb"], order["total_thb"], order["eta_days"]) == (30, 229, 2)
    order_id = order["order_id"]
    intent = s.create_payment_intent(order_id)
    assert "paid_at" not in s.view_order(order_id)
    s.approve_payment(intent["intent_id"], DEMO_PIN)
    assert s.view_order(order_id)["paid_at"] is not None


def test_every_product_image_is_self_hosted():
    from urllib.parse import urlparse

    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    for p in client.get("/api/products").json():
        res = client.get(urlparse(p["image_url"]).path)
        assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"


def test_payment_page_returns_to_zippy_only_after_approval(monkeypatch, sim):
    from urllib.parse import parse_qs, urlsplit

    from fastapi.testclient import TestClient

    from app import main, mcp_server

    s, _ = sim
    monkeypatch.setattr(main, "store", s)
    monkeypatch.setattr(mcp_server, "store", s)
    monkeypatch.setenv("SIM_RETURN_ORIGIN", "https://zippy.example")
    client = TestClient(main.app)
    order = client.post("/api/orders", json={"items": [{"product_id": "p_eyemask"}]}).json()
    order_id = order["order_id"]

    invalid = client.post(f"/api/orders/{order_id}/pay", json={
        "return_url": "https://zippy.example.evil.test/chat",
    })
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "invalid_return_url"

    intent = client.post(f"/api/orders/{order_id}/pay").json()
    payment = mcp_server.request_payment(order_id, "https://zippy.example/chat?tab=orders#latest")
    assert payment["intent_id"] == intent["intent_id"]
    assert "redirect_url" not in payment

    page = client.get(urlsplit(payment["approve_url"]).path)
    assert page.status_code == 200
    assert "SIMULATOR" in page.text

    payment_api = f"/api/payments/{payment['intent_id']}"
    wrong_pin = "000000" if DEMO_PIN != "000000" else "111111"
    assert client.post(f"{payment_api}/approve", json={"pin": wrong_pin}).status_code == 400
    assert "redirect_url" not in client.get(payment_api).json()

    receipt = client.post(f"{payment_api}/approve", json={"pin": DEMO_PIN}).json()
    assert receipt["status"] == "approved"
    redirect = urlsplit(receipt["redirect_url"])
    assert (redirect.scheme, redirect.netloc, redirect.path, redirect.fragment) == (
        "https", "zippy.example", "/chat", "latest",
    )
    assert parse_qs(redirect.query) == {
        "tab": ["orders"],
        "payment_status": ["approved"],
        "order_id": [order_id],
    }
    assert mcp_server.get_order_status(order_id)["status"] == "confirmed"


def test_search_outside_bangkok_falls_back_to_silom():
    s = Store()
    london = s.search_restaurants(lat=51.5074, lng=-0.1278)
    silom = s.search_restaurants()
    assert london and [shop["shop_id"] for shop in london] == [shop["shop_id"] for shop in silom]
    near_asok = s.search_restaurants(lat=13.7370, lng=100.5603)
    assert [shop["distance_km"] for shop in near_asok] != [shop["distance_km"] for shop in silom]
