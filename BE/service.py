import asyncio
import math
import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import urlencode

from demo import NUTRIENTS, after_minutes
from persona import lighter_orders, persona_meals, pick_meal, plan_day, weekly_recap
from recommendations import RecommendationUnavailable, food_candidates, match_catalog_food, number
from storage import read_food_catalog, read_guest_recommendation_data


MOMENTS = {"morning_sleep": "07:02", "dinner_tip": "18:15", "daily_summary": "19:40", "weekly_recap": "20:30"}
TITLES = {"morning_sleep": "Sleep insight", "dinner_tip": "Dinner tip", "daily_summary": "Daily summary",
          "weekly_recap": "Your week"}
RECAP_REPLIES = ["Plan tomorrow's meals", "Find lighter orders", "Not now"]
FOOD_SEARCH = re.compile(
    r"\b(dinner|lunch|restaurants?|nearby|near me|where to eat|shopee food|food delivery|order (?:some )?food)\b",
)
NUTRITION_LOOKUP = re.compile(r"\b(calories?|kcal|nutrition|macros?|protein|carbs?|carbohydrates?|fat)\b")
NUTRITION_CONTEXT = re.compile(
    r"\b(my|today|yesterday|logged|goal|remaining|left|burned|suggest|recommend|under|at least)\b",
)
CATALOG_NUTRIENTS = {
    "kcal": (r"\b(calories?|kcal)\b", "kcal"),
    "protein_g": (r"\bprotein\b", "g protein"),
    "carbs_g": (r"\b(carbs?|carbohydrates?)\b", "g carbs"),
    "fat_g": (r"\bfat\b", "g fat"),
}


class Zippy:
    def __init__(self, store, clock, health, shopee, prompts, coach, phone, photos, push=None, images=None):
        self.store, self.clock, self.health = store, clock, health
        self.shopee, self.prompts, self.coach = shopee, prompts, coach
        self.phone, self.photos, self.push, self.images = phone, photos, push, images
        self.tasks = set()
        self.chat_locks = defaultdict(asyncio.Lock)
        self.mutation = asyncio.Lock()
        self.recommendation_lock = asyncio.Lock()

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

    async def recommend(self, agents, kind, session_id):
        if self.recommendation_lock.locked():
            raise ValueError("A recommendation is already running for this guest.")
        async with self.recommendation_lock:
            snapshot = self.state
            items, products, restaurant_query = await agents.run(kind, self)
            async with self.mutation:
                if snapshot is not self.state:
                    raise ValueError("The guest session was reset. Trigger the recommendation again.")
                session = self.session(session_id)
                if restaurant_query:
                    session["recommended_meal"] = restaurant_query
                if products:
                    existing = {item["item_id"]: item for item in session["products"]}
                    existing.update((item["item_id"], item) for item in products)
                    session["products"] = list(existing.values())
                title, body = (
                    ("Food recommendation", "I found a meal idea for you.")
                    if kind == "food" else ("Item recommendation", "I found a Shopee Mall option for you.")
                )
                self.emit(session_id, {"text": body, "notify": {"title": title, "body": body}}, *items)
                return items

    def data_date(self):
        return self.state["date"] if self.store.demo else self.clock.now().date().isoformat()

    def personal_data(self, day):
        return read_guest_recommendation_data(self.store.database, self.store.owner, day) or {}

    def health_persona(self):
        return self.personal_data(self.data_date()).get("persona")

    def wellness(self, day, persona):
        if self.health:
            return self.health.today(self.state, day)
        yesterday = str(date.fromisoformat(day) - timedelta(days=1))
        readings = {row.get("date"): row for row in (persona or {}).get("wearable_daily", [])
                    if row.get("date") in (day, yesterday)}
        current = readings.get(day, {})
        sleep = {"minutes": None, "deep_minutes": None}
        for night in (day, yesterday):
            row = readings.get(night, {})
            hours = row.get("sleep_hours")
            minutes = row.get("sleep_minutes")
            if not isinstance(minutes, (int, float)) and isinstance(hours, (int, float)):
                minutes = hours * 60
            if isinstance(minutes, (int, float)) and 0 < minutes <= 1440:
                sleep = {"minutes": round(minutes), "deep_minutes": row.get("deep_minutes"),
                         "date": night, "source": "Imported sample" if row.get("source") == "imported_sample" else row.get("source")}
                break
        return {
            "sleep": sleep,
            "activity": {key: current.get(key) for key in ("steps", "active_minutes", "sitting_hours")},
            "recovery": {"percent": current.get("recovery_pct"), "bars": []},
        }

    def sleep_card(self):
        day = self.data_date()
        sleep = self.wellness(day, self.health_persona())["sleep"]
        goal = self.state["profile"]["goals"]["deep_minutes"]
        deep = sleep.get("deep_minutes")
        return {"kind": "sleep_insight", **sleep, "goal_minutes": goal,
                "shortfall_minutes": max(0, goal - deep) if deep is not None else None}

    def today(self):
        day = self.data_date()
        stored = self.personal_data(day)
        goals = stored.get("profile", self.state["profile"])["goals"]
        data = self.wellness(day, stored.get("persona"))
        activity = data["activity"]
        steps = activity.get("steps")
        if steps is not None:
            activity = {**activity, "steps_goal_pct": round(100 * steps / goals["steps"])}
        meals = stored.get("meals", []) + persona_meals(stored.get("persona"), day)
        return {"date": day, "now": self.now().isoformat(), **data, "activity": activity, "goals": goals,
                "totals": {key: sum(meal[key] for meal in meals) for key in NUTRIENTS},
                "upcoming": ([{"at": "18:15", "message": "Dinner idea"}] if self.store.demo else []) + [
                    {"at": order["arrival_date"], "message": "Shopee Mall eye mask delivery"}
                    for order in self.state["orders"].values()
                    if order["status"] == "paid" and order.get("fulfillment", "mall") == "mall"
                ] + [{"at": item["at"][-5:], "message": item["message"]}
                     for item in self.state["reminders"].values() if item["status"] == "scheduled"]}

    def food_log(self, day):
        stored = self.personal_data(day)
        meals = stored.get("meals", []) + persona_meals(stored.get("persona"), day)
        meals.sort(key=lambda meal: meal["time"])
        return {"date": day, "meals": meals, "totals": {key: sum(meal[key] for meal in meals) for key in NUTRIENTS},
                "suggested": None}

    def summary(self):
        today = self.today()
        values = {**today["totals"], **today["activity"], "sleep_minutes": today["sleep"]["minutes"],
                  "deep_minutes": today["sleep"]["deep_minutes"]}
        return {"kind": "daily_summary", "goals": [
            {"key": key, "value": values[key], "goal": goal,
             "met": values[key] <= goal if key in {"kcal", "carbs_g", "fat_g"} else values[key] >= goal}
            for key, goal in today["goals"].items() if values.get(key) is not None
        ]}

    async def proactive(self, moment, session_id, demo=False, resend=False):
        async with self.mutation:
            session = self.session(session_id)
            # Scheduled moments run once, but a presenter must be able to replay a
            # scene for a demo audience without resetting the entire chat.
            if moment in session["moments"] and not resend:
                return
            key = f"proactive.{moment}"
            if demo:
                self.state["clock"] = f'{self.state["date"]}T{MOMENTS[moment]}:00+07:00'
            values = {}
            items = []
            if moment == "morning_sleep":
                sleep = self.sleep_card()
                minutes = sleep["minutes"]
                items = [
                    {"card": sleep},
                ] if minutes is not None else []
            elif moment == "dinner_tip":
                today = self.today()
                protein = today["totals"]["protein_g"]
                goal = today["goals"]["protein_g"]
                values = {"protein_g": protein, "protein_goal": goal, "protein_gap": max(0, goal - protein)}
                meal, places = await self.recommend_meal(session_id, "dinner")
                items = [{"card": meal}]
                if places:
                    session["pending"] = "walk"
                    nearby = "I found one place nearby." if len(places) == 1 else f"I found {len(session['places'])} places. {places[0]['name']} has the most protein."
                    items.extend([
                        {"text": nearby, "card": self.places_card(session_id)},
                        {"card": {"kind": "activity", **today["activity"]}},
                        {"text": "Walk to dinner to get some movement in?", "quick_replies": ["Yes, I'll walk", "Not now"]},
                    ])
                else:
                    items.append({"text": "I couldn't find a place for this dish nearby."})
            elif moment == "weekly_recap":
                recap = weekly_recap(self.health_persona(), self.state["profile"]["goals"])
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
            if moment == "morning_sleep":
                if minutes is None:
                    intro = notification = "No recent sleep reading is recorded for your profile."
                else:
                    source = "The imported sample records" if sleep.get("source") == "Imported sample" else "You logged"
                    intro = f"{source} {minutes // 60} h {minutes % 60} min of sleep."
                    notification = intro
            session["moments"].append(moment)
            self.emit(session_id, {"text": intro, "notify": {
                "title": TITLES[moment],
                "body": notification,
            }}, *items)

    async def meal_card(self, meal_time="dinner"):
        """A dish that closes today's protein gap within the calories left, as a meal card."""
        today = self.today()
        protein_gap = max(0, today["goals"]["protein_g"] - today["totals"]["protein_g"])
        kcal_left = today["goals"]["kcal"] - today["totals"]["kcal"]
        persona = self.health_persona() or {"profile": {}}
        foods = read_food_catalog(self.store.database)
        choices = food_candidates(foods, persona, self.state["profile"], self.food_log(today["date"])["meals"], today["date"])
        if not choices:
            raise RecommendationUnavailable("No suitable meals were found in the MongoDB food catalog.")
        best = choices[0]
        fallback = {key: best[key] for key in ("food_id", "dish", "kcal", "protein_g")}
        fallback["why"] = "This option fits your meal preferences and nutrition goals."
        meal = pick_meal(persona, protein_gap, kcal_left, fallback, meal_time=meal_time)
        return {"kind": "meal", **await self.with_image(meal, "dishes", meal["dish"])}

    async def lookup_food_nutrition(self, query):
        foods = await asyncio.to_thread(read_food_catalog, self.store.database)
        if not foods:
            raise RecommendationUnavailable("No food catalog is configured in MongoDB.")
        food = match_catalog_food(foods, query)
        if not food:
            return None
        nutrition = food.get("nutrition") or {}
        return {"kind": "meal", "food_id": food.get("food_id"), "dish": food["menu"],
                "kcal": number(nutrition.get("calories")), "protein_g": number(nutrition.get("protein_g")),
                "carbs_g": number(nutrition.get("carbs_g")), "fat_g": number(nutrition.get("fat_g"))}

    async def recommend_meal(self, session_id, meal_time="dinner"):
        """The dinner tip: a dish, then the places that serve it."""
        meal = await self.meal_card(meal_time)
        places = await self.find_places(session_id, meal["dish"], meal["kcal"], meal["protein_g"])
        return meal, places

    async def find_products(self, session_id, query):
        """Search Shopee Mall and remember up to four results so the visitor can buy one."""
        results = await self.shopee.call("search_products", query=query)
        products = [{
            "item_id": row.get("product_id") or row["id"], "name": row["name"], "shop": row["shop"],
            "price_thb": row["price_thb"], "rating": row["rating"], "image_url": row.get("image_url"),
            "note": row.get("description") or query.capitalize(),
        } for row in results[:4]]
        self.session(session_id)["products"] = products
        return products

    def product_card(self, products):
        prices = [product["price_thb"] for product in products]
        return {"kind": "product_compare", "products": products, "best_item_id": products[0]["item_id"],
                "more": {"count": max(0, len(products) - 2), "price_range": [min(prices), max(prices)]}}

    def places_card(self, session_id, location=None):
        places = self.session(session_id)["places"]
        source = "current" if location and not self.store.demo else "silom"
        return {
            "kind": "places",
            "places": places,
            "orderable": not self.store.demo,
            "location_source": places[0].get("location_source", source) if places else source,
        }

    async def find_places(self, session_id, dish, calories=None, protein_g=None, *, location=None):
        """Find nearby Shopee Food places for a dish and remember the top three for booking or delivery."""
        coordinates = {} if self.store.demo else (location or {})
        results = await self.shopee.call(
            "find_similar_dishes", dish=dish, calories=calories, protein_g=protein_g, limit=35, **coordinates,
        )
        by_shop = {}
        for result in results:
            place = result.get("restaurant", result)
            item = result.get("item", result)
            protein = item.get("nutrition", item).get("protein_g")
            if protein is not None:
                by_shop.setdefault(place["shop_id"], {
                    "shop_id": place["shop_id"], "name": place["name"], "dish": item["name"],
                    "item_id": item.get("item_id"),
                    "protein_g": protein, "price_thb": item["price_thb"], "distance_km": place["distance_km"],
                    **({"location_source": place["location_source"]} if place.get("location_source") else {}),
                    **({"stock_image_url": place["image_url"]} if place.get("image_url") else {}),
                    **({"stock_image_credit": place["image_credit"]} if place.get("image_credit") else {}),
                })
        places = sorted(by_shop.values(), key=lambda place: (-place["protein_g"], place["distance_km"], place["price_thb"]))
        self.session(session_id)["places"] = [
            await self.with_image(place, "restaurants", place["shop_id"]) for place in places[:3]
        ]
        return places

    async def recommendation_places(self, session_id, *, location=None):
        session = self.state["sessions"].get(session_id, {})
        meal = session.get("recommended_meal")
        if not meal:
            raise LookupError("Get a meal recommendation first.")
        await self.find_places(session_id, meal["dish"], meal["calories"], meal["protein_g"], location=location)
        if session.get("recommended_meal") is meal:
            session.pop("recommended_meal")
        card = self.places_card(session_id, location)
        if not card["places"]:
            return "I didn’t find a similar Shopee Food listing nearby.", card
        text = f"These Shopee Food listings serve {meal['dish']} or a similar option."
        if meal.get("allergies"):
            text += " These listings don’t include verified allergen information."
        return text, card

    async def chat(self, session_id, message, *, location=None):
        session = self.session(session_id)
        if self.store.demo:
            location = None
        answer = message.casefold().strip().replace("’", "'")
        pending = session["pending"]
        if answer == "not now":
            session["pending"] = None
            yield {"type": "delta", "text": "Of course, Ploy." if self.store.demo else "Of course."}
        elif answer == "show me options":
            yield {"type": "tool", "name": "search_products"}
            products = await self.find_products(session_id, "eye mask")
            products.sort(key=lambda product: {"p_eyemask": 0, "p_eyemask_cotton": 1}.get(product["item_id"], 2))
            if not products:
                yield {"type": "delta", "text": "I couldn't find a matching mask on Shopee Mall."}
                return
            yield {"type": "delta", "text": f"I compared {len(products)} shops on Shopee Mall. {products[0]['note']}."}
            yield {"type": "card", "card": self.product_card(products)}
        elif session.get("recommended_meal") and answer == "skip":
            session.pop("recommended_meal")
            yield {"type": "delta", "text": "Okay."}
        elif answer.rstrip("?.!") in {"recommend places nearby", "find places for this meal"} or (
            session.get("recommended_meal") and answer.rstrip("?.!") in {
            "show me nearby restaurants", "where can i get this",
            "where can i get it", "where can i order this", "where can i order it",
            "where can i find it", "where can i buy it", "find restaurants nearby",
        }):
            if not session.get("recommended_meal"):
                yield {"type": "delta", "text": "Get a meal recommendation first."}
                return
            yield {"type": "tool", "name": "find_similar_dishes"}
            text, card = await self.recommendation_places(session_id, location=location)
            yield {"type": "delta", "text": text}
            if card["places"]:
                yield {"type": "card", "card": card}
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
        elif NUTRITION_LOOKUP.search(answer) and not NUTRITION_CONTEXT.search(answer):
            yield {"type": "tool", "name": "lookup_food_nutrition"}
            meal = await self.lookup_food_nutrition(message)
            if meal is None:
                yield {"type": "delta", "text": "I couldn’t find a matching dish in the food catalog. What’s the dish name?"}
                return
            fields = [field for field, (pattern, _) in CATALOG_NUTRIENTS.items() if re.search(pattern, answer)]
            values = [f"{meal[field]:g} {CATALOG_NUTRIENTS[field][1]}"
                      for field in (fields or CATALOG_NUTRIENTS) if meal[field] is not None]
            if values:
                text = f"The food catalog lists {', '.join(values)} for {meal['dish']}."
            else:
                text = f"The food catalog has an entry for {meal['dish']}, with no value for the nutrition you asked about."
            yield {"type": "delta", "text": text}
            yield {"type": "card", "card": meal}
        elif self.coach:
            async for event in self.coach.stream(self, session_id, message, session["history"], location=location):
                yield event
        elif not self.store.demo and FOOD_SEARCH.search(answer):
            dinner = await self.meal_card()
            yield {"type": "tool", "name": "find_similar_dishes"}
            await self.find_places(session_id, dinner["dish"], dinner["kcal"], dinner["protein_g"], location=location)
            card = self.places_card(session_id, location)
            if card["places"]:
                yield {"type": "delta", "text": f"Here are nearby places for {dinner['dish'].lower()}."}
                yield {"type": "card", "card": card}
            else:
                area = "your location" if location else "Silom, Bangkok"
                yield {"type": "delta", "text": f"I couldn't find a matching dish near {area}."}
        elif "sleep" in answer:
            sleep = self.sleep_card()
            if sleep["minutes"] is None:
                yield {"type": "delta", "text": "No recent sleep reading is recorded for your profile."}
                return
            yield {"type": "delta", "text": f"Here’s the sleep reading for {sleep.get('date') or self.data_date()}."}
            yield {"type": "card", "card": sleep}
            yield {"type": "quick_replies", "options": ["Show me options", "Not now"]}
        elif any(word in answer for word in ("step", "walk", "activity")):
            yield {"type": "delta", "text": "Here's your activity so far today."}
            yield {"type": "card", "card": {"kind": "activity", **self.today()["activity"]}}
        elif not self.store.demo and any(word in answer for word in ("recommend", "suggest")):
            today = self.today()
            profile = self.state["profile"]
            protein_left = max(0, today["goals"]["protein_g"] - today["totals"]["protein_g"])
            preferences = profile["preferences"]
            focus = f"You have {protein_left} g to go on your protein goal." if protein_left else "You've met your protein goal."
            taste = f" Use your food preferences ({preferences['food']}) to narrow it down." if preferences["food"] else ""
            yield {"type": "delta", "text": (
                f"{focus} Look for a meal with a protein source and vegetables.{taste}"
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
        persona, goals = self.health_persona(), self.state["profile"]["goals"]
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

    async def buy(self, session_id, item_id, *, kind="mall", location=None):
        async with self.mutation:
            if kind == "food":
                if self.store.demo:
                    raise ValueError("Use table booking in the Ploy demo.")
                place = next((row for row in self.session(session_id)["places"] if row.get("item_id") == item_id), None)
                if place is None:
                    raise ValueError("Choose a dish from your current Shopee Food suggestions.")
                order = await self.shopee.call(
                    "place_food_order", items=[{"item_id": item_id, "qty": 1}], **(location or {}),
                )
                item = {"item_id": item_id, "name": place["dish"], "shop": place["name"],
                        "price_thb": order["subtotal_thb"]}
                source = order.get("location_source", "current" if location else "silom")
                delivery = {"shipping_thb": order["delivery_fee_thb"], "eta_min": order["eta_min"],
                            "delivery_area": "Current location" if source == "current" else "Silom, Bangkok"}
            else:
                item = next((row for row in self.session(session_id)["products"] if row["item_id"] == item_id), None)
                if item is None:
                    raise ValueError("Choose a product from your comparison first.")
                order = await self.shopee.call("place_mall_order", items=[{"product_id": item_id, "qty": 1}])
                arrival = order.get("arrival_date")
                if not arrival and order.get("eta_days") is not None:
                    arrival = str(date.fromisoformat(self.state["date"]) + timedelta(days=order["eta_days"]))
                delivery = {"shipping_thb": order["shipping_thb"], "arrival_date": arrival,
                            "address": self.state["profile"]["preferences"]["home"]}
            summary = {"order_id": order.get("order_id") or order["id"], "fulfillment": kind,
                       "item": item, "total_thb": order["total_thb"], **delivery}
            self.state["orders"][summary["order_id"]] = {**summary, "session_id": session_id, "status": "unpaid"}
            self.store.save()
            return {"kind": "order_summary", **summary}

    def owned_order(self, session_id, order_id):
        order = self.state["orders"].get(order_id)
        if not order or order["session_id"] != session_id:
            raise LookupError("Unknown order.")
        return order

    async def payment_url(self, session_id, order_id, return_url=None):
        async with self.mutation:
            if self.owned_order(session_id, order_id)["status"] != "unpaid":
                raise ValueError("This order is no longer payable.")
            values = {"order_id": order_id}
            if return_url:
                values["return_url"] = return_url
            return await self.shopee.call("request_payment", **values)

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
            paid_states = {"paid", "confirmed", "packed", "shipped", "preparing", "rider_assigned", "picked_up", "delivered"}
            order["status"] = ("paid" if remote_status in paid_states or result.get("paid_at") is not None
                               else "cancelled" if remote_status in {"cancelled", "canceled"} else "unpaid")
            if order["status"] == "paid":
                food = order.get("fulfillment") == "food"
                receipt = {
                    "kind": "payment_status", "paid": True, "item": order["item"], "total_thb": order["total_thb"],
                    "arrival_date": order.get("arrival_date"), "eta_min": order.get("eta_min"),
                    "chips": ["Shopee Food" if food else "Shopee Mall", "Paid with ShopeePay"],
                }
                items = [{"text": "ShopeePay · approved with your PIN", "card": receipt}]
                if not food:
                    reminder = self.remind(session_id, "22:30", "Wear your eye mask")
                    items.append({"text": "I'll remind you to wear it at 10:30 tonight.", "card": reminder})
                self.emit(session_id, *items)
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
