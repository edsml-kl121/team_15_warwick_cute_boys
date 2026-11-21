"""In-memory business rules. Restarting the process deliberately resets all state."""
from __future__ import annotations

import math
import os
import time
import uuid
from threading import RLock
from urllib.parse import urlparse

from .seed import products, restaurants


class SimError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def _distance(lat1, lng1, lat2, lng2):
    r = 6371
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(math.radians(lng2-lng1)/2)**2
    return 2*r*math.asin(math.sqrt(a))


class Store:
    def __init__(self, now=time.time, base_url=""):
        self.now, self.lock = now, RLock()
        self.restaurants = restaurants(os.getenv("SIM_DEMO_PHONE", "+16502013595"))
        self.products = products(base_url.rstrip("/"))
        self.orders, self.payments = {}, {}
        self.balance = int(os.getenv("SIM_START_BALANCE", "1500"))

    def _restaurant(self, shop_id):
        return next((r for r in self.restaurants if r["shop_id"] == shop_id), None) or self._missing("shop_not_found")

    def _missing(self, code): raise SimError(code, code.replace("_", " "))

    def _food_item(self, item_id):
        for r in self.restaurants:
            for item in r["menu"]:
                if item["id"] == item_id: return r, item
        self._missing("item_not_found")

    def _with_distance(self, r, lat, lng):
        d = round(_distance(lat, lng, r["lat"], r["lng"]), 2)
        return {k:v for k,v in r.items() if k != "menu"} | {"distance_km": d, "delivery_fee_thb": round(15+8*d), "eta_min": round(15+4*d)}

    def search_restaurants(self, query="", lat=13.7246, lng=100.5293, max_km=10):
        found = [self._with_distance(r, lat, lng) for r in self.restaurants if query.lower() in (r["name"]+r["cuisine"]).lower()]
        return sorted([r for r in found if r["distance_km"] <= max_km], key=lambda r:r["distance_km"])

    def find_similar_dishes(self, dish, calories=None, protein_g=None, lat=13.7246, lng=100.5293, max_km=10, limit=10):
        words = set(dish.lower().split()); hits=[]
        for r in self.restaurants:
            info = self._with_distance(r, lat, lng)
            if info["distance_km"] > max_km: continue
            for item in r["menu"]:
                name = len(words & set(item["name"].lower().split())) / max(len(words), 1)
                macro = 1
                if calories is not None: macro -= min(abs(item["calories"]-calories)/max(calories,1), 1)/2
                if protein_g is not None: macro -= min(abs(item["protein_g"]-protein_g)/max(protein_g,1), 1)/2
                score = name if calories is None and protein_g is None else .6*name+.4*macro
                if score >= .3: hits.append({"item": item, "score": round(score, 3)} | info)
        return sorted(hits, key=lambda x:x["score"], reverse=True)[:limit]

    def get_menu(self, shop_id):
        return self._restaurant(shop_id).copy()

    def _food_quote(self, items, lat, lng):
        if not items: raise SimError("invalid_items", "at least one item is required")
        lines=[]; shop=None
        for requested in items:
            r, item = self._food_item(requested["item_id"]); qty=int(requested.get("qty",1))
            if qty < 1: raise SimError("invalid_items", "quantity must be positive")
            if shop and r["shop_id"] != shop["shop_id"]: raise SimError("multiple_restaurants", "food orders use one restaurant")
            shop= r; lines.append(item | {"qty":qty})
        d=_distance(lat,lng,shop["lat"],shop["lng"]); subtotal=sum(x["price_thb"]*x["qty"] for x in lines)
        return {"shop": self._with_distance(shop,lat,lng), "items":lines, "subtotal_thb":subtotal,
                "delivery_fee_thb":round(15+8*d), "total_thb":subtotal+round(15+8*d), "eta_min":round(15+4*d),
                "nutrition":{"calories":sum(x["calories"]*x["qty"] for x in lines), "protein_g":sum(x["protein_g"]*x["qty"] for x in lines)}}

    def quote_food_order(self, items, lat=13.7246, lng=100.5293): return self._food_quote(items,lat,lng)

    def _create(self, kind, payload):
        oid=f"o_{uuid.uuid4().hex[:10]}"; order={"id":oid,"kind":kind,"status":"pending_payment","created_at":self.now()} | payload
        self.orders[oid]=order; return order.copy()

    def place_food_order(self, items, note="", lat=13.7246, lng=100.5293):
        with self.lock: return self._create("food", self._food_quote(items,lat,lng) | {"note":note})

    def search_products(self, query="", category=None):
        terms=query.lower().split()
        return [p.copy() for p in self.products if (not category or p["category"]==category) and all(t in (p["name"]+p["category"]).lower() for t in terms)]

    def place_mall_order(self, items):
        with self.lock:
            lines=[]
            for wanted in items:
                p=next((p for p in self.products if p["id"]==wanted["product_id"]),None)
                if not p: self._missing("product_not_found")
                qty=int(wanted.get("qty",1))
                if qty < 1: raise SimError("invalid_items", "quantity must be positive")
                lines.append(p | {"qty":qty})
            subtotal=sum(x["price_thb"]*x["qty"] for x in lines); shipping=0 if subtotal>=299 else 30
            return self._create("mall", {"items":lines,"subtotal_thb":subtotal,"shipping_thb":shipping,"total_thb":subtotal+shipping,"eta_days":2})

    def request_payment(self, order_id, return_url=None):
        with self.lock:
            order=self.orders.get(order_id)
            if not order: self._missing("order_not_found")
            if order["status"] != "pending_payment": raise SimError("payment_not_allowed", "order is not awaiting payment")
            existing=next((p for p in self.payments.values() if p["order_id"]==order_id and p["status"]=="pending"),None)
            if existing:
                if return_url and not existing.get("return_url"):
                    existing = existing | {"return_url": return_url}
                    self.payments[existing["id"]] = existing
                return existing.copy()
            if return_url and urlparse(return_url).scheme not in {"http", "https"}:
                raise SimError("invalid_return_url", "return_url must use http or https")
            pid=f"pi_{uuid.uuid4().hex[:10]}"; payment={"id":pid,"order_id":order_id,"amount_thb":order["total_thb"],"status":"pending","expires_at":self.now()+600,"attempts":0,"return_url":return_url}
            self.payments[pid]=payment; return payment.copy()

    def approve_payment(self, intent_id, pin):
        with self.lock:
            p=self.payments.get(intent_id)
            if not p: self._missing("payment_not_found")
            if p["status"] != "pending": return p.copy()
            if self.now()>p["expires_at"]:
                p = p | {"status": "expired"}; self.payments[intent_id] = p; return p.copy()
            if pin != os.getenv("SIM_PIN","123456"):
                attempts = p["attempts"] + 1
                p = p | {"attempts": attempts, "status": "declined" if attempts >= 3 else "pending"}
                self.payments[intent_id] = p
                return p.copy()
            if self.balance < p["amount_thb"]:
                self.payments[intent_id] = p | {"status": "declined"}
                raise SimError("insufficient_balance", "wallet balance is too low")
            self.balance -= p["amount_thb"]
            p = p | {"status": "approved"}; self.payments[intent_id] = p
            order = self.orders[p["order_id"]] | {"paid_at": self.now(), "status": "confirmed"}
            self.orders[p["order_id"]] = order
            return p.copy()

    def decline_payment(self, intent_id):
        p=self.payments.get(intent_id)
        if not p: self._missing("payment_not_found")
        p = p | {"status": "declined"}; self.payments[intent_id] = p; return p.copy()

    def get_payment(self, intent_id):
        p=self.payments.get(intent_id)
        if not p: self._missing("payment_not_found")
        if p["status"] == "pending" and self.now() > p["expires_at"]:
            p = p | {"status": "expired"}; self.payments[intent_id] = p
        return p.copy()

    def get_order_status(self, order_id):
        order=self.orders.get(order_id)
        if not order: self._missing("order_not_found")
        result=order.copy()
        if "paid_at" in result:
            age=(self.now()-result["paid_at"])*float(os.getenv("SIM_SPEED","1")); stages=([("delivered",45),("picked_up",30),("rider_assigned",20),("preparing",8)] if result["kind"]=="food" else [("delivered",40),("shipped",20),("packed",10)])
            result["status"]=next((s for s,t in stages if age>=t),"confirmed")
            self.orders[order_id] = order | {"status": result["status"]}
        return result

    def list_orders(self): return [self.get_order_status(o) for o in sorted(self.orders, key=lambda x:self.orders[x]["created_at"], reverse=True)]
    def cancel_order(self, order_id):
        order=self.orders.get(order_id)
        if not order: self._missing("order_not_found")
        if order["status"] != "pending_payment": raise SimError("cannot_cancel", "only unpaid orders can be cancelled")
        order = order | {"status": "cancelled"}; self.orders[order_id] = order; return order.copy()
    def get_wallet_balance(self): return {"balance_thb":self.balance, "currency":"THB"}
