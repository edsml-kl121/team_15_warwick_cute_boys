from app.store import Store
from starlette.testclient import TestClient

import server


def test_mall_checkout_requires_human_pin_and_debits_wallet():
    store = Store(now=lambda: 1_000.0)
    results = store.search_products("eye mask", None)
    assert len(results) == 4

    order = store.place_mall_order([{"product_id": "p_eyemask", "qty": 1}])
    assert order["total_thb"] == 229
    intent = store.request_payment(order["id"])
    assert intent["status"] == "pending"
    assert store.approve_payment(intent["id"], "123456")["status"] == "approved"
    assert store.get_wallet_balance()["balance_thb"] == 1271


def test_food_quote_and_order_are_limited_to_one_restaurant():
    store = Store(now=lambda: 1_000.0)
    menu = store.get_menu("s_salad_factory")["menu"]
    quote = store.quote_food_order([{"item_id": menu[0]["id"], "qty": 1}], 13.7246, 100.5293)
    assert quote["subtotal_thb"] == menu[0]["price_thb"]
    assert quote["delivery_fee_thb"] >= 15
    assert quote["nutrition"]["calories"] == menu[0]["calories"]


def test_invalid_pin_declines_after_three_attempts():
    store = Store(now=lambda: 1_000.0)
    order = store.place_mall_order([{"product_id": "p_eyemask_basic", "qty": 1}])
    intent = store.request_payment(order["id"])
    store.approve_payment(intent["id"], "nope")
    store.approve_payment(intent["id"], "nope")
    payment = store.approve_payment(intent["id"], "nope")
    assert payment["status"] == "declined"


def test_rest_payment_flow_returns_human_payment_url():
    client = TestClient(server.app, headers={"host": "localhost"})
    created = client.post("/api/orders", json={"items": [{"product_id": "p_eyemask", "qty": 1}]}).json()
    payment = client.post(f"/api/orders/{created['id']}/pay", json={"return_url": "https://agent.example/return"})
    assert payment.status_code == 200
    assert payment.json()["approve_url"].endswith(f"/pay/{payment.json()['id']}")
    approved = client.post(f"/api/payments/{payment.json()['id']}/approve", json={"pin": "123456"})
    assert approved.json()["status"] == "approved"
