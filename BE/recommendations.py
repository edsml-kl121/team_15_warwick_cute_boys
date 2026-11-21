import asyncio
import json
import math
import re
from collections import Counter
from datetime import date, timedelta
from difflib import SequenceMatcher
from statistics import mean
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel

from persona import persona_meals
from storage import read_food_catalog, read_guest_recommendation_data


class RecommendationUnavailable(Exception):
    pass


class BucketRecommendationData:
    """Sign private images for foods stored in MongoDB."""

    def __init__(self, client, bucket):
        self.client = client
        self.bucket = bucket

    @classmethod
    def connect(cls, bucket, region, endpoint, addressing_style):
        import boto3
        from botocore.config import Config

        client = boto3.client("s3", region_name=region, endpoint_url=endpoint, config=Config(
            signature_version="s3v4", s3={"addressing_style": addressing_style}, connect_timeout=5, read_timeout=10,
            retries={"total_max_attempts": 2},
        ))
        return cls(client, bucket)

    async def catalog_image_url(self, foods, food_id, dish):
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



class Choice(BaseModel):
    choice: int


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def words(value):
    return set(re.findall(r"[^\W_]+", str(value).casefold()))


def match_catalog_food(foods, query):
    """Find a named dish in a question, tolerating modest spelling errors."""
    tokens = re.findall(r"[^\W_]+", query.casefold())
    message = " ".join(tokens)
    ranked = []
    for food in foods:
        name = re.findall(r"[^\W_]+", food.get("menu", "").casefold())
        size = len(name)
        if not size or size > len(tokens):
            continue
        label = " ".join(name)
        if f" {label} " in f" {message} ":
            confidence = 1.0
        elif size >= 2:
            confidence = max(SequenceMatcher(None, label, " ".join(tokens[i:i + size])).ratio()
                             for i in range(len(tokens) - size + 1))
            if confidence < 0.83:
                continue
        else:
            continue
        ranked.append((confidence + 0.02 * min(size, 5), food))
    ranked.sort(key=lambda candidate: candidate[0], reverse=True)
    if not ranked or len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.01:
        return None
    return ranked[0][1]


def wearable_summary(persona, day):
    start = str(date.fromisoformat(day) - timedelta(days=13))
    readings = sorted((row for row in persona.get("wearable_daily", []) if start <= str(row.get("date", "")) <= day),
                      key=lambda row: row["date"])[-7:]
    result = {}
    if any(row.get("source") == "imported_sample" for row in readings):
        result["imported_sample"] = True
    sleep = []
    for row in readings:
        minutes = number(row.get("sleep_minutes"))
        hours = minutes / 60 if minutes is not None else number(row.get("sleep_hours"))
        if hours is not None and 0 < hours <= 24:
            sleep.append((row["date"], hours))
    if sleep:
        result["sleep_hours"] = round(mean(hours for _, hours in sleep), 1)
        result["sleep_nights"] = len(sleep)
        yesterday = str(date.fromisoformat(day) - timedelta(days=1))
        for recorded, hours in sleep:
            if recorded == yesterday:
                result["yesterday_sleep_hours"] = hours
    for field in ("active_minutes", "steps", "recovery_pct"):
        valid = [row[field] for row in readings if number(row.get(field)) is not None
                 and row[field] >= 0]
        if valid:
            result[field] = round(mean(valid), 1)
    return result


async def load_recommendation_context(visitor, database):
    """Read the current guest's profile, meals, and wearable history from MongoDB."""
    day = visitor.data_date()
    try:
        stored = await asyncio.to_thread(read_guest_recommendation_data, database, visitor.store.owner, day)
    except Exception:
        raise RecommendationUnavailable("Couldn’t read the guest’s recommendation data from MongoDB.") from None
    if stored is None:
        raise RecommendationUnavailable("No MongoDB guest record is available for this session.")
    persona = stored.get("persona") or {"profile": {}}
    return stored["profile"], persona, wearable_summary(persona, day), stored["meals"], day


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



def meal_reason(meal, logged, goals):
    logged_protein = sum(item["protein_g"] for item in logged)
    if any(item.get("source") == "imported_sample" for item in logged):
        return (f"The imported sample meal history totals {logged_protein:g} g of protein. "
                f"This meal would add {meal['protein_g']} g toward your {goals['protein_g']} g goal.",
                ["food_log", "profile"])
    remaining_kcal = goals["kcal"] - sum(item["kcal"] for item in logged)
    if logged and logged_protein < goals["protein_g"]:
        remaining = goals["protein_g"] - logged_protein
        reason = (f"Your meal history shows {logged_protein:g} g of protein today, with {remaining:g} g left toward "
                  f"your goal. This meal adds {meal['protein_g']} g.")
    elif logged and meal["kcal"] <= remaining_kcal:
        reason = f"Your meal history leaves {remaining_kcal:g} kcal for today, and this serving fits."
    elif logged:
        reason = "I looked for a meal you hadn’t logged today. You’ve already reached your protein goal."
    else:
        reason = f"I picked this to help you reach your {goals['protein_g']} g daily protein goal."
        if meal["kcal"] <= goals["kcal"]:
            reason += f" One serving fits within your {goals['kcal']:,} kcal target."
    references = ["food_log", "profile"] if logged or meal["logged_before"] else ["profile"]
    if meal["logged_before"]:
        count = meal["logged_before"]
        reason += f" You’ve logged this dish {count} {'time' if count == 1 else 'times'} before."
    elif meal["cuisine_match"]:
        reason += f" It matches your preference for {meal['cuisine']} food."
    return reason, references


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
        catalog = await self.food_catalog()
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
        why, references = meal_reason(chosen, logged, profile["goals"])
        meal = {key: chosen[key] for key in ("food_id", "dish", "kcal", "protein_g")}
        items = [{
            "card": {"kind": "meal", **meal, "why": why},
            "references": references,
            "quick_replies": ["Recommend places nearby", "Skip"],
        }]
        restaurant_query = {
            "dish": meal["dish"], "calories": meal["kcal"], "protein_g": meal["protein_g"],
            "allergies": bool(source.get("allergies")),
        }
        return items, [], restaurant_query

    async def item(self, zippy, profile, wearable):
        sleep_goal = profile["goals"]["sleep_minutes"]
        yesterday_sleep = wearable.get("yesterday_sleep_hours")
        sleep_hours = yesterday_sleep if yesterday_sleep is not None else wearable.get("sleep_hours")
        sample = wearable.get("imported_sample")
        choices = []
        if sleep_hours is not None and sleep_hours * 60 < sleep_goal:
            nights = wearable["sleep_nights"]
            shortfall = round(sleep_goal - sleep_hours * 60)
            recorded = f"Your wearable recorded {sleep_hours:.2g} hours of sleep yesterday." if yesterday_sleep is not None else (
                f"Your wearable logged an average of {sleep_hours:g} hours of sleep across "
                f"{nights} recorded {'night' if nights == 1 else 'nights'}."
            )
            if sample:
                recorded = f"An imported sample records {sleep_hours:.2g} hours of sleep."
            choices.append({"query": "eye mask", "references": ["health_data"], "reason": (
                f"{recorded} That’s about {max(1, shortfall)} minutes below your {sleep_goal / 60:g}-hour goal. "
                "An eye mask can help block room light."
            )})
        if wearable.get("active_minutes", 0) >= profile["goals"]["active_minutes"]:
            source = "The imported sample shows" if sample else "Your wearable recorded"
            choices.append({"query": "foam roller", "references": ["health_data"], "reason": (
                f"{source} about {wearable['active_minutes']:g} active minutes a day. "
                "A foam roller is an option for a post-workout wind-down."
            )})
        if not choices and sleep_hours is not None:
            period = "yesterday" if yesterday_sleep is not None and not sample else "on average"
            source = "The imported sample shows" if sample else "Your wearable logged"
            choices.append({"query": "eye mask", "references": ["health_data"], "reason": (
                f"{source} {sleep_hours:.2g} hours of sleep {period}, meeting your "
                f"{sleep_goal / 60:g}-hour goal. An eye mask is optional if room light bothers you."
            )})
        if not choices:
            raise ValueError("No qualifying sleep or activity readings were found in your history.")
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
        return [{"text": chosen["reason"] + comparison, "references": chosen["references"]}, {"card": card}], products, None

    async def run(self, kind, zippy):
        profile, persona, wearable, logged, day = await load_recommendation_context(zippy, self.database)
        if kind == "food":
            return await self.food(zippy, persona, profile, wearable, logged, day)
        return await self.item(zippy, profile, wearable)

    async def food_catalog(self):
        try:
            foods = await asyncio.to_thread(read_food_catalog, self.database)
        except Exception:
            raise RecommendationUnavailable("Couldn’t read the food catalog from MongoDB.") from None
        if not foods:
            raise RecommendationUnavailable("No food catalog is configured in MongoDB.")
        return foods

    async def catalog_image_url(self, food_id, dish):
        if not self.data or not (food_id or dish):
            return None
        return await self.data.catalog_image_url(await self.food_catalog(), food_id, dish)

    async def health_history(self, zippy, start, end):
        _, persona, _, _, _ = await load_recommendation_context(zippy, self.database)
        history = {}
        for field in ("wearable_daily", "workouts", "weights", "body_composition_scans"):
            rows = []
            for row in persona.get(field, []):
                raw_date = row.get("date") or row.get("timestamp") or row.get("start_time")
                try:
                    recorded = date.fromisoformat(str(raw_date)[:10])
                except ValueError:
                    continue
                if start <= recorded <= end:
                    rows.append(row)
            history[field] = rows
        return history
