import asyncio
import json
import math
import re
from collections import Counter
from datetime import date, timedelta
from statistics import mean
from time import monotonic
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel

from persona import apply_to_profile, persona_meals
from storage import read_guest_recommendation_data


class RecommendationUnavailable(Exception):
    pass


class BucketRecommendationData:
    """Read the hackathon dataset and cache its JSON objects for five minutes."""

    def __init__(self, client, bucket):
        self.client = client
        self.bucket = bucket
        self.cache = {}

    @classmethod
    def connect(cls, bucket, region, endpoint, addressing_style):
        import boto3
        from botocore.config import Config

        client = boto3.client("s3", region_name=region, endpoint_url=endpoint, config=Config(
            signature_version="s3v4", s3={"addressing_style": addressing_style}, connect_timeout=5, read_timeout=10,
            retries={"total_max_attempts": 2},
        ))
        return cls(client, bucket)

    async def read(self, key):
        expires, data = self.cache.get(key, (0, None))
        if expires > monotonic():
            return data

        def read_object():
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
            with body:
                content = body.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                raise ValueError("Recommendation data exceeds the supported object size.")
            return json.loads(content)

        try:
            data = await asyncio.to_thread(read_object)
        except Exception:
            raise RecommendationUnavailable("Couldn’t read the recommendation data from the bucket.") from None
        self.cache[key] = (monotonic() + 300, data)
        return data

    async def catalog_image_url(self, food_id, dish):
        foods = (await self.read("body_data/food_db.json"))["foods"]
        matches = [food for food in foods if (
            str(food.get("food_id")) == food_id if food_id else food.get("menu", "").casefold() == dish.casefold()
        )]
        if len(matches) != 1 or not matches[0].get("image_url"):
            return None
        endpoint = urlsplit(self.client.meta.endpoint_url)
        image = urlsplit(matches[0]["image_url"])
        if image.scheme != "https" or image.username or image.password:
            return None
        # Accept only object URLs for this catalog bucket.
        path = unquote(image.path.removeprefix("/"))
        if image.netloc == endpoint.netloc and path.startswith(f"{self.bucket}/"):
            path = path.removeprefix(f"{self.bucket}/")
        elif image.netloc != f"{self.bucket}.{endpoint.netloc}":
            return None
        if not path.startswith("food_db/") or any(part in {"", ".", ".."} for part in path.split("/")):
            return None
        if not path.casefold().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            return None
        return await asyncio.to_thread(
            self.client.generate_presigned_url, "get_object",
            Params={"Bucket": self.bucket, "Key": path}, ExpiresIn=900,
        )

    async def persona(self, guest_name, *, food):
        profiles = (await self.read("body_data/user_profiles.json"))["personas"]
        matches = [p for p in profiles if p["display_name"].strip().casefold() == guest_name.strip().casefold()]
        if len(matches) != 1:
            return None
        profile = matches[0]
        persona_id = profile["persona_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", persona_id):
            raise RecommendationUnavailable("The bucket contains an invalid persona ID.")

        def find_file():
            result = self.client.list_objects_v2(Bucket=self.bucket, Prefix=f"personas/{persona_id}_", MaxKeys=10)
            keys = [item["Key"] for item in result.get("Contents", []) if item["Key"].endswith(".json")]
            if len(keys) != 1 or result.get("IsTruncated"):
                raise ValueError("Expected one persona file.")
            return keys[0]

        try:
            key = await asyncio.to_thread(find_file)
        except Exception:
            raise RecommendationUnavailable("Couldn’t find the guest’s persona file in the bucket.") from None
        keys = [key, "body_data/body_health_wearable.json"]
        if food:
            keys.append("body_data/food_history_log.json")
        persona, health, *history = await asyncio.gather(*(self.read(path) for path in keys))
        if persona["profile"]["persona_id"] != persona_id:
            raise RecommendationUnavailable("The bucket persona doesn’t match the selected guest.")
        body = next((entry for entry in health.get("body", []) if entry.get("persona_id") == persona_id), {})
        return {
            **persona,
            **{name: body[name] for name in ("weights", "body_composition_scans") if name in body},
            "wearable_daily": [entry for entry in health["daily"] if entry.get("persona_id") == persona_id]
            or persona.get("wearable_daily", []),
            "food_history_log": (
                [entry for entry in history[0]["entries"] if entry.get("persona_id") == persona_id]
                or persona.get("food_history_log", [])
            ) if history else [],
        }


class Choice(BaseModel):
    choice: int


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def words(value):
    return set(re.findall(r"[^\W_]+", str(value).casefold()))


def wearable_summary(persona, day):
    start = str(date.fromisoformat(day) - timedelta(days=13))
    readings = sorted((row for row in persona.get("wearable_daily", []) if start <= row.get("date", "") <= day),
                      key=lambda row: row["date"])[-7:]
    result = {}
    for field in ("sleep_hours", "active_minutes", "steps", "recovery_pct"):
        valid = [row[field] for row in readings if number(row.get(field)) is not None
                 and (0 < row[field] <= 24 if field == "sleep_hours" else row[field] >= 0)]
        if valid:
            result[field] = round(mean(valid), 1)
            if field == "sleep_hours":
                result["sleep_nights"] = len(valid)
    return result


async def load_recommendation_context(visitor, bucket, *, food, database=None):
    """Combine guest-scoped Mongo history and bucket data for either agent."""
    state = visitor.state
    day = state["date"]
    profile, persona = state["profile"], state.get("persona")
    logged = {meal["id"]: meal for meal in state["food"]
              if meal["date"] == day and not meal["id"].startswith("seed-")}
    owner = getattr(visitor.store, "owner", None)
    if database is None:
        database = getattr(visitor.store, "database", None)
    if database is not None and owner:
        try:
            stored = await asyncio.to_thread(read_guest_recommendation_data, database, owner, day)
        except Exception:
            raise RecommendationUnavailable("Couldn’t read the guest’s recommendation data from MongoDB.") from None
        if stored:
            profile = stored.get("profile") or profile
            persona = stored.get("persona") or persona
            logged.update((meal["id"], meal) for meal in stored["meals"] if not meal["id"].startswith("seed-"))

    if not persona and bucket is not None:
        persona = await bucket.persona(profile["name"], food=food)
        if persona:
            profile = apply_to_profile(profile, persona)
    persona = persona or {"profile": {}}
    return profile, persona, wearable_summary(persona, day), list(logged.values()), day


def food_candidates(catalog, persona, profile, logged, day):
    source = persona["profile"]
    cutoff = str(date.fromisoformat(day) - timedelta(days=7))
    history = [entry for entry in persona.get("food_history_log", []) if entry.get("date", "") <= day]
    familiar = Counter(str(item.get("catalog_food_id")) for entry in history for item in entry.get("items", []))
    recent = Counter(str(item.get("catalog_food_id")) for entry in history if entry.get("date", "") >= cutoff
                     for item in entry.get("items", []))
    favourites = words(" ".join(source.get("favorite_dishes", [])))
    cuisine = words(" ".join(source.get("cuisine_prefs", [])) + " " + profile["preferences"]["food"])
    allergies = words(" ".join(source.get("allergies") or []))
    for aliases, tag in [({"milk", "lactose"}, "dairy"), ({"wheat", "celiac"}, "gluten"),
                         ({"nuts", "almonds", "cashews", "walnuts"}, "tree_nut"),
                         ({"shrimp", "prawns", "crab"}, "shellfish"), ({"peanuts"}, "peanut"),
                         ({"eggs"}, "egg"), ({"soya"}, "soy")]:
        if allergies & aliases:
            allergies.update(words(tag))
    goals = profile["goals"]
    kcal_left = goals["kcal"] - sum(meal["kcal"] for meal in logged)
    protein_left = max(0, goals["protein_g"] - sum(meal["protein_g"] for meal in logged))
    target = max(250, min(round(goals["kcal"] * 0.35), kcal_left if logged and kcal_left > 0 else goals["kcal"]))
    protein_target = min(round(goals["protein_g"] * 0.4), protein_left)
    already_logged = {meal["dish"].casefold() for meal in logged}
    ranked = []
    for food in catalog:
        if food.get("role") not in {"main", "salad", "soup"} or not food.get("menu"):
            continue
        nutrition = food.get("nutrition") or {}
        kcal, protein = number(nutrition.get("calories")), number(nutrition.get("protein_g"))
        if kcal is None or protein is None or kcal <= 0 or protein < 0:
            continue
        if logged and kcal_left > 0 and kcal > kcal_left:
            continue
        if allergies & words(" ".join(food.get("allergens") or [])):
            continue
        if food["menu"].casefold() in already_logged:
            continue
        food_id = str(food.get("food_id"))
        cuisine_match = bool(food.get("cuisine") and cuisine & words(food["cuisine"]))
        preference = cuisine_match or len(words(food["menu"]) & favourites) >= 2
        score = (abs(kcal - target) / max(target, 1) + max(0, protein_target - protein) / max(protein_target, 1)
                 - 0.3 * preference - 0.08 * min(familiar[food_id], 3) + 0.15 * min(recent[food_id], 3))
        ranked.append((score, {
            "food_id": food.get("food_id"), "dish": food["menu"], "kcal": round(kcal), "protein_g": round(protein),
            "cuisine": food.get("cuisine"), "cuisine_match": cuisine_match, "diet_flags": food.get("diet_flags", []),
            "logged_before": familiar[food_id], "recent_count": recent[food_id],
        }))
    return [food for _, food in sorted(ranked, key=lambda pair: pair[0])[:12]]


def meal_reason(meal, logged, wearable, goals):
    logged_protein = sum(item["protein_g"] for item in logged)
    remaining_kcal = goals["kcal"] - sum(item["kcal"] for item in logged)
    if logged and logged_protein < goals["protein_g"]:
        remaining = goals["protein_g"] - logged_protein
        reason = (f"Your food log shows {logged_protein:g} g of protein today. You have {remaining:g} g left toward "
                  f"today’s protein goal, and this meal would add about {meal['protein_g']} g.")
    else:
        share = round(100 * meal["protein_g"] / goals["protein_g"])
        reason = f"This serving covers about {share}% of the {goals['protein_g']} g daily protein goal in your profile."
    if logged and meal["kcal"] <= remaining_kcal:
        reason += f" At {meal['kcal']} kcal, it fits within the {remaining_kcal:g} kcal left in your food log."
    elif not logged:
        reason += f" It uses about {meal['kcal']} of your {goals['kcal']:,} daily kcal."
    if meal["logged_before"]:
        count = meal["logged_before"]
        reason += f" You’ve logged this dish {count} {'time' if count == 1 else 'times'} before."
    elif meal["cuisine_match"]:
        reason += f" It also matches your preference for {meal['cuisine']} food."
    elif wearable.get("active_minutes", 0) > 0:
        reason += f" Your wearable recorded about {wearable['active_minutes']:g} active minutes a day recently."
    return reason


class RecommendationAgents:
    def __init__(self, data, prompts, model=None, database=None):
        self.data = data
        self.prompts = prompts
        self.model = model
        self.database = database

    async def choose(self, kind, context, candidates):
        if not self.model:
            return candidates[0]
        from openai import AsyncOpenAI

        try:
            async with AsyncOpenAI(timeout=25, max_retries=0) as client:
                response = await client.responses.parse(
                    model=self.model, store=False, max_output_tokens=150,
                    instructions=self.prompts.get(f"recommendation.{kind}"), text_format=Choice,
                    input=json.dumps({"context": context, "choices": candidates}, ensure_ascii=False),
                )
            chosen = response.output_parsed
            if chosen is not None and 0 <= chosen.choice < len(candidates):
                return candidates[chosen.choice]
        except Exception:
            raise RecommendationUnavailable("The recommendation model is unavailable. Try again.") from None
        raise RecommendationUnavailable("The model returned an invalid recommendation. Try again.")

    async def food(self, zippy, persona, profile, wearable, logged, day):
        if self.data is None:
            raise RecommendationUnavailable("Configure the recommendation bucket to use the food catalog.")
        catalog = (await self.data.read("body_data/food_db.json"))["foods"]
        logged = persona_meals(persona, day) + logged
        candidates = food_candidates(catalog, persona, profile, logged, day)
        if not candidates:
            raise ValueError("No catalog meals fit the guest’s logged meals and preferences.")
        source = persona["profile"]
        chosen = await self.choose("food", {
            "goals": {key: profile["goals"][key] for key in ("kcal", "protein_g")},
            "logged_today": {key: sum(meal[key] for meal in logged) for key in ("kcal", "protein_g")},
            "cuisines": source.get("cuisine_prefs", [])[:10], "diet": source.get("diet_preset"),
            "preferences": profile["preferences"]["food"], "body_goal": source.get("body_goal"),
            "recent_activity": {key: wearable[key] for key in ("steps", "active_minutes") if key in wearable},
        }, candidates)
        why = meal_reason(chosen, logged, wearable, profile["goals"])
        area = source.get("home_area") or {}
        lat, lng = number(area.get("lat")), number(area.get("lng"))
        location = {"lat": lat, "lng": lng} if lat is not None and lng is not None else {}
        try:
            hits = await zippy.shopee.call("find_similar_dishes", dish=chosen["dish"], calories=chosen["kcal"],
                                           protein_g=chosen["protein_g"], limit=35, **location)
        except Exception:
            raise RecommendationUnavailable("Shopee Food listings are unavailable. Try again.") from None
        places = {}
        for hit in hits:
            restaurant = hit.get("restaurant") or {}
            nutrition = hit.get("nutrition") or {}
            price = number(hit.get("price_thb"))
            if not restaurant.get("shop_id") or price is None:
                continue
            places.setdefault(restaurant["shop_id"], {
                "shop_id": restaurant["shop_id"], "name": restaurant["name"], "dish": hit["name"],
                "protein_g": nutrition.get("protein_g"), "price_thb": price,
                "distance_km": restaurant.get("distance_km"),
            })
            if len(places) == 3:
                break
        meal = {key: chosen[key] for key in ("food_id", "dish", "kcal", "protein_g")}
        items = [{"card": {"kind": "meal", **meal, "why": why}}]
        if places:
            text = "These Shopee Food listings serve this dish or a similar option."
            if source.get("allergies"):
                text += " These listings don’t include verified allergen information."
            items.append({"text": text, "card": {"kind": "places", "places": list(places.values())}})
        else:
            items.append({"text": "I didn’t find a similar Shopee Food listing nearby."})
        return items, []

    async def item(self, zippy, profile, wearable):
        sleep_goal = profile["goals"]["sleep_minutes"] / 60
        choices = []
        if "sleep_hours" in wearable and wearable["sleep_hours"] < sleep_goal:
            nights = wearable["sleep_nights"]
            shortfall = round((sleep_goal - wearable["sleep_hours"]) * 60)
            choices.append({"query": "eye mask", "reason": (
                f"You averaged about {wearable['sleep_hours']:g} hours of sleep across "
                f"{nights} recorded {'night' if nights == 1 else 'nights'}, below your {sleep_goal:g}-hour goal "
                f"by about {max(1, shortfall)} minutes on average. "
                "An eye mask is worth considering if room light makes it harder to sleep."
            )})
        elif zippy.store.demo and not wearable:
            sleep = zippy.sleep_card()["minutes"]
            if sleep < profile["goals"]["sleep_minutes"]:
                choices.append({"query": "eye mask", "reason": "You slept less than your goal last night. "
                                "An eye mask can block room light if it’s disturbing your sleep."})
        if wearable.get("active_minutes", 0) >= profile["goals"]["active_minutes"]:
            choices.append({"query": "foam roller", "reason": (
                f"Your wearable recorded about {wearable['active_minutes']:g} active minutes a day recently. "
                "A foam roller is an option for a post-workout wind-down."
            )})
        if not choices:
            choices.append({"query": "eye mask", "reason": (
                "A general sleep accessory to consider. An eye mask can help block room light if it bothers you."
            )})
        chosen = await self.choose("item", {"signals": wearable}, choices)
        try:
            hits = await zippy.shopee.call("search_products", query=chosen["query"])
        except Exception:
            raise RecommendationUnavailable("Shopee Mall listings are unavailable. Try again.") from None
        products = [{
            "item_id": row.get("product_id") or row["id"], "name": row["name"], "shop": row["shop"],
            "price_thb": row["price_thb"], "rating": row["rating"], "image_url": row.get("image_url"),
            "note": row.get("description"),
        } for row in hits[:4]]
        if not products:
            raise ValueError("Shopee Mall didn’t return a matching product.")
        products.sort(key=lambda product: (-product["rating"], product["price_thb"]))
        card = {"kind": "product_compare", "products": products, "best_item_id": products[0]["item_id"]}
        best = products[0]
        comparison = (f" {best['name']} is the highest-rated match I found "
                      f"({best['rating']:g}/5, ฿{best['price_thb']:g}).") if len(products) > 1 else ""
        return [{"text": chosen["reason"] + comparison}, {"card": card}], products

    async def run(self, kind, zippy):
        profile, persona, wearable, logged, day = await load_recommendation_context(
            zippy, self.data, food=kind == "food", database=self.database,
        )
        if kind == "food":
            return await self.food(zippy, persona, profile, wearable, logged, day)
        return await self.item(zippy, profile, wearable)
