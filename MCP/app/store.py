"""In-memory Shopee simulator: food, mall, ShopeePay wallet, order lifecycle.

Shared by the MCP tools (agent side) and the REST/UI routes (human side).
State resets on restart, which is what a demo wants.
"""

import math
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit

from mcp.server.mcpserver.exceptions import ToolError

from app.seed import DEFAULT_LOCATION, MALL_PRODUCTS, NUTRIENTS, RESTAURANTS, product

# Explicit PUBLIC_BASE_URL wins; on Railway fall back to the domain it injects automatically.
_railway = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
PUBLIC_BASE_URL = (
    os.getenv("PUBLIC_BASE_URL", "").strip().strip('"').rstrip("/")
    or (f"https://{_railway}" if _railway else "http://localhost:8090")
)

DEMO_USER = "demo"
DEMO_PIN = os.getenv("SIM_PIN", "123456")
START_BALANCE = float(os.getenv("SIM_START_BALANCE", "1500"))
# >1 makes orders progress faster. 1.0 = food delivered ~45s after payment.
SPEED = float(os.getenv("SIM_SPEED", "1"))
MAX_PIN_ATTEMPTS = 3
INTENT_TTL_S = 600
MALL_ETA_DAYS = 2

FOOD_STAGES = [
    (0, "confirmed"),
    (8, "preparing"),
    (20, "rider_assigned"),
    (30, "picked_up"),
    (45, "delivered"),
]
MALL_STAGES = [(0, "confirmed"), (10, "packed"), (20, "shipped"), (40, "delivered")]


class SimError(ToolError):
    """Business-rule failure. `code` is stable for agents to branch on."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _km(a: dict, b: dict) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(h))


def _delivery(km: float) -> tuple[float, int]:
    """(fee_thb, eta_min). Flat 15 THB + 8/km, 15 min + 4 min/km."""
    return round(15 + 8 * km), round(15 + 4 * km)


STOPWORDS = {"with", "and", "the", "of", "on", "in", "a", "or", "set", "l", "special", "regular"}
MIN_MATCH = 0.3
NAME_WEIGHT = 0.6  # rest goes to nutrition closeness when targets are given


def _words(text: str) -> set[str]:
    # ponytail: word overlap with naive plural strip, no synonyms or Thai; swap for embeddings if matches feel dumb
    tokens = re.findall(r"[a-z]+", text.lower())
    return {t[:-1] if len(t) > 3 and t.endswith("s") else t for t in tokens} - STOPWORDS


def _closeness(actual: dict, targets: dict) -> float:
    scores = [max(0.0, 1 - abs(actual[k] - t) / t) for k, t in targets.items() if t]
    return sum(scores) / len(scores)


def _here(lat: float | None, lng: float | None) -> dict:
    return (
        {"lat": lat, "lng": lng}
        if lat is not None and lng is not None
        else DEFAULT_LOCATION
    )


def _validate_return_url(return_url: str) -> None:
    """A payment page may send users back only to the configured Zippy origin."""
    allowed_origin = os.getenv("SIM_RETURN_ORIGIN", "").strip().rstrip("/")
    try:
        if any(ch.isspace() or ord(ch) < 32 or ch == "\\" for ch in return_url):
            raise ValueError
        url = urlsplit(return_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or f"{url.scheme}://{url.netloc}" != allowed_origin
        ):
            raise ValueError
    except ValueError:
        raise SimError(
            "invalid_return_url", "Return URL must match the configured SIM_RETURN_ORIGIN"
        ) from None


class Store:
    def __init__(self, now: Callable[[], float] = time.time):
        self.now = now
        self._lock = (
            threading.RLock()
        )  # ponytail: one global lock, fine for a single-process demo
        # SIM_DEMO_PHONE sends every booking call to one number (e.g. a teammate) on stage.
        demo_phone = os.getenv("SIM_DEMO_PHONE", "").strip()
        self.shops = {
            r["shop_id"]: {
                **{k: v for k, v in r.items() if k != "menu"},
                **({"phone": demo_phone} if demo_phone else {}),
            }
            for r in RESTAURANTS
        }
        self.items = {
            item["item_id"]: item for r in RESTAURANTS for item in r["menu"]
        }
        self.products = {}
        for row in MALL_PRODUCTS:
            p = product(row)
            self.products[p["product_id"]] = {**p, "image_url": PUBLIC_BASE_URL + p["image_path"]}
        self.wallets = {DEMO_USER: START_BALANCE}
        self.orders: dict[str, dict] = {}
        self.intents: dict[str, dict] = {}

    # ---------- Shopee Food ----------

    def search_restaurants(
        self,
        query: str = "",
        lat: float | None = None,
        lng: float | None = None,
        max_km: float = 10,
    ) -> list[dict]:
        here = _here(lat, lng)
        q = query.lower().strip()
        out = []
        for shop in self.shops.values():
            menu = [i for i in self.items.values() if i["shop_id"] == shop["shop_id"]]
            haystack = " ".join(
                [shop["name"], shop["cuisine"], *(i["name"] for i in menu)]
            ).lower()
            km = _km(here, shop)
            if (q and q not in haystack) or km > max_km:
                continue
            fee, eta = _delivery(km)
            out.append(
                {
                    **shop,
                    "distance_km": round(km, 1),
                    "delivery_fee_thb": fee,
                    "eta_min": eta,
                    "price_range_thb": [
                        min(i["price_thb"] for i in menu),
                        max(i["price_thb"] for i in menu),
                    ],
                }
            )
        return sorted(out, key=lambda s: s["distance_km"])

    def find_similar_dishes(
        self,
        dish: str,
        calories: float | None = None,
        protein_g: float | None = None,
        lat: float | None = None,
        lng: float | None = None,
        max_km: float = 10,
        limit: int = 10,
    ) -> list[dict]:
        wanted = _words(dish)
        targets = {"calories": calories, "protein_g": protein_g}
        has_targets = any(targets.values())
        nearby = {s["shop_id"]: s for s in self.search_restaurants("", lat, lng, max_km)}
        hits = []
        for item in self.items.values():
            shop = nearby.get(item["shop_id"])
            if not shop:
                continue
            name_score = len(wanted & _words(item["name"])) / len(wanted) if wanted else 0
            score = (
                NAME_WEIGHT * name_score
                + (1 - NAME_WEIGHT) * _closeness(item["nutrition"], targets)
                if has_targets
                else name_score
            )
            if score >= MIN_MATCH:
                hits.append({**item, "match_score": round(score, 2), "restaurant": dict(shop)})
        hits.sort(key=lambda h: (-h["match_score"], h["restaurant"]["distance_km"]))
        return hits[:limit]

    def get_menu(self, shop_id: str) -> dict:
        shop = self.shops.get(shop_id)
        if not shop:
            raise SimError("shop_not_found", f"No shop {shop_id}")
        return {
            **shop,
            "menu": [i for i in self.items.values() if i["shop_id"] == shop_id],
        }

    # ---------- Shopee Mall ----------

    def search_products(self, query: str = "", category: str = "") -> list[dict]:
        q = query.lower().strip()
        return [
            p
            for p in self.products.values()
            if (not q or q in f"{p['name']} {p['description']} {p['category']}".lower())
            and (not category or p["category"] == category)
        ]

    # ---------- Orders ----------

    def _lines(self, items: list[dict], catalog: dict, kind: str) -> list[dict]:
        if not items:
            raise SimError("empty_order", "Order needs at least one item")
        lines = []
        for entry in items:
            key = entry.get("item_id") or entry.get("product_id")
            qty = int(entry.get("qty", 1))
            src = catalog.get(key)
            if not src:
                raise SimError("item_not_found", f"No {kind} item {key}")
            if not 1 <= qty <= 20:
                raise SimError("bad_qty", f"qty for {key} must be 1-20")
            lines.append(
                {
                    "id": key,
                    "name": src["name"],
                    "qty": qty,
                    "unit_price_thb": src["price_thb"],
                    "nutrition": src.get("nutrition"),
                    "shop_id": src.get("shop_id"),
                    **({"shop": src["shop"]} if kind == "mall" else {}),
                }
            )
        return lines

    def quote_food(
        self, items: list[dict], lat: float | None = None, lng: float | None = None
    ) -> dict:
        lines = self._lines(items, self.items, "menu")
        shop_ids = {line["shop_id"] for line in lines}
        if len(shop_ids) != 1:
            raise SimError("multi_shop", "All items must come from one shop")
        shop = self.shops[shop_ids.pop()]
        fee, eta = _delivery(_km(_here(lat, lng), shop))
        return self._quote("food", lines, fee, eta, shop)

    def quote_mall(self, items: list[dict]) -> dict:
        lines = self._lines(items, self.products, "mall")
        subtotal = sum(line["unit_price_thb"] * line["qty"] for line in lines)
        shipping = 0 if subtotal >= 299 else 30
        return {
            **self._quote("mall", lines, shipping, MALL_ETA_DAYS * 24 * 60, None),
            "shipping_thb": shipping,
            "eta_days": MALL_ETA_DAYS,
        }

    def _quote(
        self, kind: str, lines: list[dict], fee: float, eta: int, shop: dict | None
    ) -> dict:
        subtotal = sum(line["unit_price_thb"] * line["qty"] for line in lines)
        nutrition = None
        if kind == "food":
            nutrition = {
                k: sum(line["nutrition"][k] * line["qty"] for line in lines)
                for k in NUTRIENTS
            }
        return {
            "kind": kind,
            "shop_id": shop and shop["shop_id"],
            "shop_name": shop and shop["name"],
            "items": lines,
            "subtotal_thb": subtotal,
            "delivery_fee_thb": fee,
            "total_thb": subtotal + fee,
            "eta_min": eta,
            "nutrition_total": nutrition,
        }

    def place_order(
        self,
        kind: str,
        items: list[dict],
        user_id: str = DEMO_USER,
        note: str = "",
        lat: float | None = None,
        lng: float | None = None,
    ) -> dict:
        if kind not in ("food", "mall"):
            raise SimError("bad_kind", "kind must be food or mall")
        quote = (
            self.quote_food(items, lat, lng)
            if kind == "food"
            else self.quote_mall(items)
        )
        order = {
            **quote,
            "order_id": _id("ord"),
            "user_id": user_id,
            "note": note[:200],
            "status": "pending_payment",
            "created_at": self.now(),
            "paid_at": None,
            "intent_id": None,
            "notified": False,
        }
        with self._lock:
            self.orders[order["order_id"]] = order
        return self.view_order(order["order_id"])

    def cancel_order(self, order_id: str) -> dict:
        with self._lock:
            order = self._order(order_id)
            if order["status"] != "pending_payment":
                raise SimError(
                    "not_cancellable", f"Order is {self.view_order(order_id)['status']}"
                )
            self.orders[order_id] = {**order, "status": "cancelled"}
            if order["intent_id"]:
                intent = self.intents[order["intent_id"]]
                self.intents[intent["intent_id"]] = {**intent, "status": "cancelled"}
        return self.view_order(order_id)

    def _order(self, order_id: str) -> dict:
        order = self.orders.get(order_id)
        if not order:
            raise SimError("order_not_found", f"No order {order_id}")
        return order

    def view_order(self, order_id: str) -> dict:
        """Order with its live status. Post-payment status is derived from elapsed time."""
        order = self._order(order_id)
        status, progress = order["status"], []
        if status == "paid":
            stages = FOOD_STAGES if order["kind"] == "food" else MALL_STAGES
            elapsed = (self.now() - order["paid_at"]) * SPEED
            progress = [{"status": s, "done": elapsed >= t} for t, s in stages]
            status = [s for t, s in stages if elapsed >= t][-1]
        public = {k: v for k, v in order.items() if k != "notified"}
        if public["paid_at"] is None:
            del public["paid_at"]
        return {**public, "status": status, "progress": progress}

    def list_orders(self, user_id: str = DEMO_USER) -> list[dict]:
        ids = [o["order_id"] for o in self.orders.values() if o["user_id"] == user_id]
        return sorted(
            (self.view_order(i) for i in ids),
            key=lambda o: o["created_at"],
            reverse=True,
        )

    # ---------- ShopeePay ----------

    def wallet(self, user_id: str = DEMO_USER) -> dict:
        return {"user_id": user_id, "balance_thb": self.wallets.get(user_id, 0.0)}

    def create_payment_intent(self, order_id: str, return_url: str | None = None) -> dict:
        """Agent asks for payment. Only a human with the PIN can approve it (REST/UI)."""
        if return_url is not None:
            _validate_return_url(return_url)
        with self._lock:
            order = self._order(order_id)
            if order["status"] != "pending_payment":
                raise SimError("not_payable", f"Order is {order['status']}")
            if (
                order["intent_id"]
                and self._intent(order["intent_id"])["status"] == "pending"
            ):
                intent_id = order["intent_id"]
                existing = self.intents[intent_id]
                if return_url is not None:
                    if existing.get("return_url") not in {None, return_url}:
                        raise SimError("return_url_mismatch", "Payment already has a return URL")
                    self.intents[intent_id] = {**existing, "return_url": return_url}
                return self._intent_view(intent_id)
            intent = {
                "intent_id": _id("pi"),
                "order_id": order_id,
                "user_id": order["user_id"],
                "amount_thb": order["total_thb"],
                "status": "pending",
                "attempts": 0,
                "created_at": self.now(),
                "return_url": return_url,
            }
            self.intents[intent["intent_id"]] = intent
            self.orders[order_id] = {**order, "intent_id": intent["intent_id"]}
        return self._intent_view(intent["intent_id"])

    def _intent(self, intent_id: str) -> dict:
        intent = self.intents.get(intent_id)
        if not intent:
            raise SimError("intent_not_found", f"No payment {intent_id}")
        if (
            intent["status"] == "pending"
            and self.now() - intent["created_at"] > INTENT_TTL_S
        ):
            intent = {**intent, "status": "expired"}
            self.intents[intent_id] = intent
        return intent

    def _intent_view(self, intent_id: str) -> dict:
        intent = self._intent(intent_id)
        return_url = intent.get("return_url")
        view = {key: value for key, value in intent.items() if key != "return_url"}
        view["approve_path"] = f"/pay/{intent_id}"
        if intent["status"] == "approved" and return_url:
            url = urlsplit(return_url)
            params = [
                (key, value)
                for key, value in parse_qsl(url.query, keep_blank_values=True)
                if key not in {"payment_status", "order_id"}
            ]
            params.extend([("payment_status", "approved"), ("order_id", intent["order_id"])])
            view["redirect_url"] = url._replace(query=urlencode(params)).geturl()
        return view

    def get_payment(self, intent_id: str) -> dict:
        with self._lock:
            intent = self._intent_view(intent_id)
            return {**intent, "order": self.view_order(intent["order_id"])}

    def approve_payment(self, intent_id: str, pin: str) -> dict:
        with self._lock:
            intent = self._intent(intent_id)
            if intent["status"] != "pending":
                raise SimError("not_pending", f"Payment is {intent['status']}")
            if pin != DEMO_PIN:
                attempts = intent["attempts"] + 1
                locked = attempts >= MAX_PIN_ATTEMPTS
                self.intents[intent_id] = {
                    **intent,
                    "attempts": attempts,
                    "status": "declined" if locked else "pending",
                }
                raise SimError(
                    "wrong_pin",
                    "Too many wrong PINs, payment declined"
                    if locked
                    else f"Wrong PIN, {MAX_PIN_ATTEMPTS - attempts} tries left",
                )
            balance = self.wallets.get(intent["user_id"], 0.0)
            if balance < intent["amount_thb"]:
                self.intents[intent_id] = {**intent, "status": "declined"}
                raise SimError(
                    "insufficient_funds", f"Balance {balance} < {intent['amount_thb']}"
                )
            self.wallets[intent["user_id"]] = balance - intent["amount_thb"]
            self.intents[intent_id] = {**intent, "status": "approved"}
            order = self.orders[intent["order_id"]]
            self.orders[order["order_id"]] = {
                **order,
                "status": "paid",
                "paid_at": self.now(),
            }
        return self.get_payment(intent_id)

    def decline_payment(self, intent_id: str) -> dict:
        with self._lock:
            intent = self._intent(intent_id)
            if intent["status"] != "pending":
                raise SimError("not_pending", f"Payment is {intent['status']}")
            self.intents[intent_id] = {**intent, "status": "declined"}
        return self.get_payment(intent_id)

    # ---------- Delivery webhook feed ----------

    def take_newly_delivered(self) -> list[dict]:
        """Delivered orders not yet announced; marks them announced."""
        out = []
        with self._lock:
            for order_id, order in list(self.orders.items()):
                if order["notified"] or order["status"] != "paid":
                    continue
                view = self.view_order(order_id)
                if view["status"] == "delivered":
                    self.orders[order_id] = {**order, "notified": True}
                    out.append(view)
        return out


store = Store()
