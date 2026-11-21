import asyncio
import math
import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import urlencode

from demo import DINNER, NUTRIENTS, after_minutes
from persona import lighter_orders, persona_meals, pick_meal, plan_day, weekly_recap


MOMENTS = {"morning_sleep": "07:02", "dinner_tip": "18:15", "daily_summary": "19:40", "weekly_recap": "20:30"}
TITLES = {"morning_sleep": "Sleep insight", "dinner_tip": "Dinner tip", "daily_summary": "Daily summary",
          "weekly_recap": "Your week"}
RECAP_REPLIES = ["Plan tomorrow's meals", "Find lighter orders", "Not now"]


class Zippy:
    def __init__(self, store, clock, health, shopee, prompts, coach, phone, photos, push=None, images=None):
        self.store, self.clock, self.health = store, clock, health
        self.shopee, self.prompts, self.coach = shopee, prompts, coach
        self.phone, self.photos, self.push, self.images = phone, photos, push, images
        self.tasks = set()
        self.chat_locks = defaultdict(asyncio.Lock)
        self.mutation = asyncio.Lock()

    @property
    def state(self):
        return self.store.state

    def now(self):
        return self.clock.now(self.state)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def session(self, session_id):
        return self.state["sessions"].setdefault(session_id, {
            "feed": [], "history": [], "moments": [], "products": [], "places": [], "pending": None,
            "timeline": [], "updated_at": self.now().isoformat(),
        })

    def record_event(self, session, **event):
        timeline = session.setdefault("timeline", [])
        at = self.now().isoformat()
        session["updated_at"] = at
        timeline.append({"seq": len(timeline) + 1, "at": at, **event})

    def emit(self, session_id, *items):
        session = self.session(session_id)
        feed = session["feed"]
        for item in items:
            entry = {"id": len(feed) + 1, "at": self.now().isoformat(), "role": "assistant", **item}
            feed.append(entry)
            self.record_event(session, type="feed", item=entry)
        self.store.save()
        for item in items:
            if item.get("notify") and self.push and self.state.get("push_subscriptions"):
                self.spawn(self.deliver(item["notify"]))

    async def deliver(self, notification):
        """Send a notification to the visitor's devices and forget devices the push service dropped."""
        gone = await self.push.send(list(self.state["push_subscriptions"]), notification)
        if gone:
            async with self.mutation:
                self.state["push_subscriptions"] = [
                    item for item in self.state.get("push_subscriptions", []) if item["endpoint"] not in gone]
                self.store.save()

    def sleep_card(self):
        sleep = self.health.today(self.state, self.state["date"])["sleep"]
        goal = self.state["profile"]["goals"]["deep_minutes"]
        return {"kind": "sleep_insight", **sleep, "goal_minutes": goal,
                "shortfall_minutes": max(0, goal - sleep["deep_minutes"])}

    def today(self):
        date = self.state["date"]
        goals = self.state["profile"]["goals"]
        data = self.health.today(self.state, date)
        activity = {**data["activity"], "steps_goal_pct": round(100 * data["activity"]["steps"] / goals["steps"])}
        return {"date": date, "now": self.now().isoformat(), "demo_data": True, **data, "activity": activity, "goals": goals,
                "totals": self.food_log(date)["totals"],
                "upcoming": ([{"at": "18:15", "message": "Dinner idea"}] if self.store.demo else []) + [
                    {"at": order["arrival_date"], "message": "Shopee Mall eye mask delivery"}
                    for order in self.state["orders"].values() if order["status"] == "paid"
                ] + [{"at": item["at"][-5:], "message": item["message"]}
                     for item in self.state["reminders"].values() if item["status"] == "scheduled"]}

    def food_log(self, date):
        meals = [meal for meal in self.state["food"] if meal["date"] == date] + persona_meals(self.state.get("persona"), date)
        return {"date": date, "meals": meals, "totals": {key: sum(meal[key] for meal in meals) for key in NUTRIENTS},
                "suggested": DINNER if self.store.demo and date == self.state["date"] else None}

    def summary(self):
        today = self.today()
        values = {**today["totals"], **today["activity"], "sleep_minutes": today["sleep"]["minutes"],
                  "deep_minutes": today["sleep"]["deep_minutes"]}
        return {"kind": "daily_summary", "goals": [
            {"key": key, "value": values[key], "goal": goal,
             "met": values[key] <= goal if key in {"kcal", "carbs_g", "fat_g"} else values[key] >= goal}
            for key, goal in today["goals"].items()
        ]}

    async def proactive(self, moment, session_id, demo=False):
        async with self.mutation:
            session = self.session(session_id)
            if moment in session["moments"]:
                return
            key = f"proactive.{moment}"
            if demo:
                self.state["clock"] = f'{self.state["date"]}T{MOMENTS[moment]}:00+07:00'
            values = {}
            items = []
            if moment == "morning_sleep":
                items = [
                    {"card": self.sleep_card()},
                    {"text": self.prompts.get(f"{key}.follow_up"), "quick_replies": ["Show me options", "Not now"]},
                ]
            elif moment == "dinner_tip":
                today = self.today()
                protein = today["totals"]["protein_g"]
                goal = today["goals"]["protein_g"]
                values = {"protein_g": protein, "protein_goal": goal, "protein_gap": max(0, goal - protein)}
                kcal_left = today["goals"]["kcal"] - today["totals"]["kcal"]
                dinner = pick_meal(self.state.get("persona"), values["protein_gap"], kcal_left, DINNER)
                places = await self.find_places(session_id, dinner["dish"], dinner["kcal"], dinner["protein_g"])
                items = [{"card": {"kind": "meal", **await self.with_image(dinner, "dishes", dinner["dish"])}}]
                if places:
                    session["pending"] = "walk"
                    nearby = "I found one place nearby." if len(places) == 1 else f"I found {len(session['places'])} places. {places[0]['name']} has the most protein."
                    items.extend([
                        {"text": nearby, "card": {"kind": "places", "places": session["places"]}},
                        {"card": {"kind": "activity", **today["activity"]}},
                        {"text": "Walk to dinner to get some movement in?", "quick_replies": ["Yes, I'll walk", "Not now"]},
                    ])
                else:
                    items.append({"text": "I couldn't find a place for this dish within your budget."})
            elif moment == "weekly_recap":
                recap = weekly_recap(self.state.get("persona"), self.state["profile"]["goals"])
                name = self.state["profile"]["name"]
                if recap:
                    values = {"days": recap["days"], "name": name, "headline": recap["insight"]}
                    session["pending"] = "recap"
                    items = [{"card": recap},
                             {"text": f"{recap['insight']} What should we work on?", "quick_replies": RECAP_REPLIES}]
                else:
                    values = {"days": 7, "name": name, "headline": "Import your health history to get a weekly recap."}
                    items = [{"text": "Import your health history in Profile and I'll recap your week here."}]
            else:
                items = [{"card": self.summary()}]
            notification = self.prompts.render(f"{key}.notification", **values)
            intro = self.prompts.render(f"{key}.intro", **values)
            session["moments"].append(moment)
            self.emit(session_id, {"text": intro, "notify": {
                "title": TITLES[moment],
                "body": notification,
            }}, *items)

    async def find_places(self, session_id, dish, calories=None, protein_g=None):
        """Find nearby Shopee Food places for a dish within budget and remember the top three for booking."""
        results = await self.shopee.call("find_similar_dishes", dish=dish, calories=calories, protein_g=protein_g, limit=35)
        budget = self.state["profile"]["preferences"]["budget_thb"]
        by_shop = {}
        for result in results:
            place = result.get("restaurant", result)
            item = result.get("item", result)
            protein = item.get("nutrition", item).get("protein_g")
            if protein is not None and item["price_thb"] <= budget:
                by_shop.setdefault(place["shop_id"], {
                    "shop_id": place["shop_id"], "name": place["name"], "dish": item["name"],
                    "protein_g": protein, "price_thb": item["price_thb"], "distance_km": place["distance_km"],
                    **({"stock_image_url": place["image_url"]} if place.get("image_url") else {}),
                })
        places = sorted(by_shop.values(), key=lambda place: (-place["protein_g"], place["distance_km"], place["price_thb"]))
        self.session(session_id)["places"] = [
            await self.with_image(place, "restaurants", place["shop_id"]) for place in places[:3]
        ]
        return places

    async def chat(self, session_id, message):
        session = self.session(session_id)
        answer = message.casefold().strip().replace("’", "'")
        pending = session["pending"]
        if answer == "not now":
            session["pending"] = None
            yield {"type": "delta", "text": "Of course, Ploy." if self.store.demo else "Of course."}
        elif answer == "show me options":
            yield {"type": "tool", "name": "search_products"}
            results = await self.shopee.call("search_products", query="eye mask")
            products = [{
                "item_id": row.get("product_id") or row["id"], "name": row["name"], "shop": row["shop"],
                "price_thb": row["price_thb"], "rating": row["rating"], "image_url": row.get("image_url"),
                "note": row.get("description") or "Sleep eye mask",
            } for row in results[:4]]
            products.sort(key=lambda product: {"p_eyemask": 0, "p_eyemask_cotton": 1}.get(product["item_id"], 2))
            if not products:
                yield {"type": "delta", "text": "I couldn't find a matching mask on Shopee Mall."}
                return
            best = products[0]
            session["products"] = products
            yield {"type": "delta", "text": f"I compared {len(products)} shops on Shopee Mall. {best['note']}."}
            prices = [product["price_thb"] for product in products]
            yield {"type": "card", "card": {"kind": "product_compare", "products": products,
                   "best_item_id": best["item_id"], "more": {"count": max(0, len(products) - 2),
                   "price_range": [min(prices), max(prices)]}}}
        elif pending == "walk" and answer in {"yes", "yes, i'll walk", "i'll walk"}:
            session["pending"] = "book"
            name = session["places"][0]["name"]
            yield {"type": "delta", "text": f"Nice. I can call {name}. Book a table for 1 at 7 pm?"}
            yield {"type": "quick_replies", "options": ["Yes, book it", "Not now"]}
        elif pending == "book" and answer in {"yes", "yes, book it", "book it"}:
            yield {"type": "tool", "name": "book_table_by_phone"}
            booking = await self.book(session_id, session["places"][0]["shop_id"])
            session["pending"] = None
            yield {"type": "delta", "text": f"Calling {booking['restaurant_name']} now."}
        elif pending == "retry" and session.get("alternate") and answer == f"call {session['alternate']['name']}".casefold():
            yield {"type": "tool", "name": "book_table_by_phone"}
            booking = await self.book(session_id, session["alternate"]["shop_id"])
            session["pending"] = None
            yield {"type": "delta", "text": f"Calling {booking['restaurant_name']} now."}
        elif answer in {"plan tomorrow's meals", "find lighter orders"}:
            for event in self.recap_answer(answer):
                yield event
        elif self.coach:
            async for event in self.coach.stream(self, session_id, message, session["history"]):
                yield event
        elif "sleep" in answer:
            yield {"type": "delta", "text": "Here's last night, from the moment you fell asleep."}
            yield {"type": "card", "card": self.sleep_card()}
            yield {"type": "quick_replies", "options": ["Show me options", "Not now"]}
        elif any(word in answer for word in ("step", "walk", "activity")):
            yield {"type": "delta", "text": "Here's your activity so far today."}
            yield {"type": "card", "card": {"kind": "activity", **self.today()["activity"]}}
        elif not self.store.demo and any(word in answer for word in ("dinner", "recommend", "suggest")):
            today = self.today()
            profile = self.state["profile"]
            protein_left = max(0, today["goals"]["protein_g"] - today["totals"]["protein_g"])
            preferences = profile["preferences"]
            focus = f"You have {protein_left} g to go on your protein goal." if protein_left else "You've met your protein goal."
            taste = f" Use your food preferences ({preferences['food']}) to narrow it down." if preferences["food"] else ""
            yield {"type": "delta", "text": (
                f"{focus} Look for a meal with a protein source and vegetables within ฿{preferences['budget_thb']}.{taste}"
            )}
        elif any(word in answer for word in ("protein", "calorie", "food", "meal")):
            today = self.today()
            yield {"type": "delta", "text": f"You've logged {today['totals']['protein_g']} g of protein and {today['totals']['kcal']:,} kcal today."}
        else:
            yield {"type": "delta", "text": "You can ask me about last night's sleep, today's activity, or your meals."}

    async def with_image(self, record, folder, name):
        """A copy of the record with a bucket picture when one is uploaded, keeping any image it already has."""
        url = await self.images.find(folder, name) if self.images else None
        return {**record, "image_url": url} if url else record

    def recap_answer(self, answer):
        """Rule-based follow-ups to the weekly recap, built from the imported history."""
        persona, goals = self.state.get("persona"), self.state["profile"]["goals"]
        if not persona:
            yield {"type": "delta", "text": "Import your health history in Profile first, then I can plan from it."}
            return
        if answer == "plan tomorrow's meals":
            plan = plan_day(persona, goals)
            if not plan:
                yield {"type": "delta", "text": "I couldn't find enough logged meals to build a plan yet."}
                return
            rows = "\n".join(f"| {meal['meal']} | {meal['dish']} | {meal['kcal']:,} | {meal['protein_g']} g |" for meal in plan)
            kcal, protein = sum(meal["kcal"] for meal in plan), sum(meal["protein_g"] for meal in plan)
            yield {"type": "delta", "text": (
                f"Here's a day built from meals you already eat, aiming for **{goals['kcal']:,} kcal** and "
                f"**{goals['protein_g']} g protein**:\n\n| Meal | Dish | kcal | Protein |\n|---|---|---|---|\n{rows}\n\n"
                f"Total: {kcal:,} kcal · {protein} g protein.")}
            yield {"type": "quick_replies", "options": ["Find lighter orders", "Not now"]}
            return
        picks = lighter_orders(persona)
        if not picks:
            yield {"type": "delta", "text": "I don't see enough Shopee Food orders to compare yet."}
            return
        lines = "\n".join(f"- **{dish['dish']}** at {dish['restaurant']} · {dish['kcal']:,} kcal · {dish['protein_g']} g protein"
                          for dish in picks)
        yield {"type": "delta", "text": f"Your go-to orders with the most protein per calorie:\n\n{lines}"}
        yield {"type": "quick_replies", "options": ["Plan tomorrow's meals", "Not now"]}

    async def buy(self, session_id, item_id):
        async with self.mutation:
            product = next((item for item in self.session(session_id)["products"] if item["item_id"] == item_id), None)
            if product is None:
                raise ValueError("Choose a product from your comparison first.")
            order = await self.shopee.call("place_mall_order", items=[{"product_id": item_id, "qty": 1}])
            arrival = order.get("arrival_date")
            if not arrival and order.get("eta_days") is not None:
                arrival = str(date.fromisoformat(self.state["date"]) + timedelta(days=order["eta_days"]))
            order = {"order_id": order.get("order_id") or order["id"], "item": product,
                     "shipping_thb": order["shipping_thb"], "total_thb": order["total_thb"],
                     "arrival_date": arrival, "address": self.state["profile"]["preferences"]["home"]}
            self.state["orders"][order["order_id"]] = {**order, "session_id": session_id, "status": "unpaid"}
            self.store.save()
            return {"kind": "order_summary", **order}

    def owned_order(self, session_id, order_id):
        order = self.state["orders"].get(order_id)
        if not order or order["session_id"] != session_id:
            raise LookupError("Unknown order.")
        return order

    async def payment_url(self, session_id, order_id):
        async with self.mutation:
            if self.owned_order(session_id, order_id)["status"] != "unpaid":
                raise ValueError("This order is no longer payable.")
            return await self.shopee.call("request_payment", order_id=order_id)

    async def order_status(self, session_id, order_id, cancel=False):
        async with self.mutation:
            order = self.owned_order(session_id, order_id)
            if order["status"] != "unpaid":
                return {"status": order["status"]}
            result = await self.shopee.call("get_order_status", order_id=order_id)
            if cancel and result["status"] in {"unpaid", "pending_payment"}:
                try:
                    result = await self.shopee.call("cancel_order", order_id=order_id)
                except ValueError:
                    result = await self.shopee.call("get_order_status", order_id=order_id)
                    if result["status"] in {"unpaid", "pending_payment"}:
                        raise
            remote_status = result["status"]
            order["status"] = ("paid" if remote_status in {"paid", "confirmed", "packed", "shipped", "delivered"}
                               or "paid_at" in result else "cancelled" if remote_status in {"cancelled", "canceled"} else "unpaid")
            if order["status"] == "paid":
                reminder = self.remind(session_id, "22:30", "Wear your eye mask")
                self.emit(session_id, {"text": "ShopeePay · approved with your PIN",
                    "card": {"kind": "payment_status", "paid": True, "item": order["item"], "total_thb": order["total_thb"],
                             "arrival_date": order["arrival_date"], "chips": ["Shopee Mall", "Paid with ShopeePay"]}},
                    {"text": "I'll remind you to wear it at 10:30 tonight.", "card": reminder})
            else:
                self.store.save()
            return {"status": order["status"]}

    def remind(self, session_id, time, message, *, route=None):
        reminder_id = uuid.uuid4().hex
        self.state["reminders"][reminder_id] = {
            "id": reminder_id, "at": f'{self.state["date"]}T{time}', "message": message,
            "status": "scheduled", "session_id": session_id, "route": route,
        }
        return {"kind": "reminder", "at": time, "message": message}

    def due_reminders(self, force=None):
        now = self.now().strftime("%Y-%m-%dT%H:%M")
        for reminder in self.state["reminders"].values():
            if reminder["status"] != "scheduled":
                continue
            if (force and reminder["at"][-5:] != force) or (not force and reminder["at"] > now):
                continue
            reminder["status"] = "sent"
            title = "Time to go" if reminder["route"] else "Reminder"
            item = {"text": reminder["message"], "notify": {"title": title, "body": reminder["message"]}}
            if reminder["route"]:
                item["card"] = reminder["route"]
            self.emit(reminder["session_id"], item)

    async def book(self, session_id, shop_id, time="19:00", party_size=1, request=None):
        async with self.mutation:
            if any(item["status"] in {"calling", "in_call"} for item in self.state["bookings"].values()):
                raise ValueError("A booking call is already in progress.")
            listing = next((item for item in self.session(session_id)["places"] if item["shop_id"] == shop_id), None)
            if listing is None:
                raise ValueError("Choose a restaurant from the suggested places first.")
            if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", time) or not 1 <= party_size <= 20:
                raise ValueError("Give the time as HH:MM and a party size from 1 to 20.")
            if time <= self.now().strftime("%H:%M"):
                raise ValueError("That time has already passed today. Choose a later time.")
            place = await self.shopee.call("get_menu", shop_id=shop_id)
            self.phone.validate(place.get("phone", ""))
            booking_id = uuid.uuid4().hex
            booking = {
                "id": booking_id, "shop_id": shop_id, "restaurant_name": place["name"], "phone": place.get("phone", ""),
                "party_size": party_size, "time": time, "name": self.state["profile"]["name"], "status": "calling",
                "request": (request or f"a table for {party_size} at {time}").strip()[:300],
                "call_sid": None, "duration_s": None, "quote": None, "created_at": self.now().isoformat(),
                "session_id": session_id, "distance_km": listing["distance_km"],
                "maps_query": place.get("address") or f"{place['name']} Bangkok",
            }
            self.state["bookings"][booking_id] = booking
            self.emit(session_id, {"header_status": "calling"})
            self.spawn(self.start_call(booking))
            return booking

    async def start_call(self, booking):
        try:
            await self.phone.start(self, booking)
        except Exception:
            await self.finish_call(booking["id"], "failed")

    def call_connected(self, booking_id):
        booking = self.state["bookings"].get(booking_id)
        if booking and booking["status"] == "calling":
            booking["status"] = "in_call"
            self.emit(booking["session_id"], {"header_status": "in_call"})

    async def finish_call(self, booking_id, status, duration=None):
        if hasattr(self.phone, "discard"):
            await self.phone.discard(booking_id)
        async with self.mutation:
            booking = self.state["bookings"].get(booking_id)
            if not booking or booking["status"] not in {"calling", "in_call"}:
                return
            booking["status"] = status
            booking["duration_s"] = duration
            session_id = booking["session_id"]
            card = {"kind": "call", "restaurant": booking["restaurant_name"], "duration_s": duration,
                    "status": "no_answer" if status == "no_answer" else "ended", "quote": booking["quote"], "outcome": status}
            items = [{"card": card, "header_status": "online"}]
            session = self.session(session_id)
            if status == "booked":
                minutes = math.ceil(booking["distance_km"] * 12)
                leave_by = after_minutes(booking["time"], -minutes - 2)
                query = urlencode({"api": 1, "destination": booking["maps_query"], "travelmode": "walking"})
                route = {"kind": "walk_route", "minutes": minutes, "leave_by": leave_by,
                         "maps_url": "https://www.google.com/maps/dir/?" + query}
                reminder = self.remind(session_id, leave_by, f"Time to go. {minutes} min walk, route is on your lock screen.", route=route)
                items += [
                    {"text": f"Done, they'll hold it under {booking['name']}.", "card": route},
                    {"text": f"Leave by {leave_by}. I'll nudge you when it's time.", "card": reminder},
                ]
            else:
                called = {item["shop_id"] for item in self.state["bookings"].values() if item["session_id"] == session_id}
                alternatives = [place for place in session["places"] if place["shop_id"] not in called]
                opening = {"no_answer": "No answer.", "full": "They're full.", "failed": "I couldn't complete the booking."}[status]
                if alternatives:
                    alternate = min(alternatives, key=lambda place: place["distance_km"])
                    minutes = round(12 * (booking["distance_km"] - alternate["distance_km"]))
                    distance = f" is {minutes} min closer and has a similar menu" if minutes > 0 else " has a similar menu"
                    session["pending"] = "retry"
                    session["alternate"] = alternate
                    items.append({"text": f"{opening} {alternate['name']}{distance}. Call them instead?",
                                  "quick_replies": [f"Call {alternate['name']}"]})
                else:
                    items.append({"text": opening})
            self.emit(session_id, *items)

    async def reset(self):
        async with self.mutation:
            if any(item["status"] in {"calling", "in_call"} for item in self.state["bookings"].values()):
                raise ValueError("Wait for the booking call to end before resetting.")
            for order in self.state["orders"].values():
                if order["status"] == "unpaid":
                    remote = await self.shopee.call("get_order_status", order_id=order["order_id"])
                    if remote["status"] in {"unpaid", "pending_payment"}:
                        try:
                            await self.shopee.call("cancel_order", order_id=order["order_id"])
                        except ValueError:
                            remote = await self.shopee.call("get_order_status", order_id=order["order_id"])
                            if remote["status"] in {"unpaid", "pending_payment"}:
                                raise
            self.store.reset(self.state["date"])
