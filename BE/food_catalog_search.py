"""Index public menu descriptions and retrieve canonical MongoDB nutrition for chat."""

import asyncio
import json
import logging
import os
import re
from hashlib import sha256

from openai import AsyncOpenAI, OpenAIError
from pymongo.errors import PyMongoError

from storage import read_food_catalog


ACTIVE_INDEX = "openai_food_search"
logger = logging.getLogger(__name__)
RESULT_LIMIT = 20
MENU_FIELDS = ("menu", "menu_th", "description", "ingredients", "cuisine", "allergens", "diet_flags")
NUTRITION_FIELDS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg")
FOOD_QUERY = re.compile(
    r"\b(food|dish(?:es)?|eat|meal|breakfast|lunch|dinner|snacks?|menus?|calories?|kcal|nutrition|"
    r"macros?|protein|carbs?|rice|noodles?|pasta|chicken|pork|beef|vegetarian|vegan|catalog)\b",
    re.IGNORECASE,
)


def catalog_documents(foods):
    documents = []
    identifiers = set()
    for food in foods:
        food_id = str(food["food_id"])
        if not food_id or food_id in identifiers:
            raise ValueError("Food catalog IDs must be nonempty and unique.")
        identifiers.add(food_id)
        text = json.dumps({key: food[key] for key in MENU_FIELDS if food.get(key)}, ensure_ascii=False, sort_keys=True)
        documents.append((food_id, text))
    return sorted(documents)


def nutrition_context(food):
    values = food.get("nutrition") or {}
    return {
        "food_id": str(food["food_id"]), "dish": food["menu"],
        "nutrition": {key: values[key] for key in NUTRITION_FIELDS if isinstance(values.get(key), (int, float))},
    }


class FoodCatalogSearch:
    def __init__(self, database):
        self.database = database

    async def search(self, query):
        try:
            return await self._search(query)
        except (OpenAIError, PyMongoError) as error:
            logger.warning("Managed food catalog search unavailable (%s).", type(error).__name__)
            return []

    async def _search(self, query):
        index = await asyncio.to_thread(
            self.database.food_catalog.find_one, {"_id": ACTIVE_INDEX}, {"vector_store_id": 1},
        )
        if not index:
            return []
        async with AsyncOpenAI(api_key=os.getenv("FOOD_SEARCH_OPENAI_API_KEY") or None, timeout=8, max_retries=0) as client:
            page = await client.vector_stores.search(
                index["vector_store_id"], query=query, max_num_results=RESULT_LIMIT,
            )
        ids = dict.fromkeys(
            str(hit.attributes["food_id"]) for hit in page.data if (hit.attributes or {}).get("food_id")
        )
        foods = await asyncio.to_thread(read_food_catalog, self.database)
        by_id = {str(food["food_id"]): food for food in foods}
        return [nutrition_context(by_id[key]) for key in ids if key in by_id]


async def build_index(database):
    """Upload one small file per dish and publish the index only after all files are ready."""
    collection = database.food_catalog
    documents = catalog_documents(read_food_catalog(database))
    if not documents:
        raise ValueError("No food catalog is configured in MongoDB.")
    revision = sha256(json.dumps(documents, ensure_ascii=False).encode()).hexdigest()
    build_id = f"{ACTIVE_INDEX}:{revision}"
    async with AsyncOpenAI(timeout=45, max_retries=4) as client:
        active = collection.find_one({"_id": ACTIVE_INDEX})
        if active and active.get("revision") == revision:
            return active["vector_store_id"], active["food_count"]
        progress = collection.find_one({"_id": build_id})
        if not progress:
            store = await client.vector_stores.create(name=f"Zippy food catalog {revision[:12]}")
            progress = {"_id": build_id, "vector_store_id": store.id, "uploads": {}}
            collection.insert_one(progress)
        store_id = progress["vector_store_id"]
        uploads = progress["uploads"]

        async def upload(food_id, content):
            key = sha256(food_id.encode()).hexdigest()
            file = await client.files.create(file=(f"{key}.txt", content.encode(), "text/plain"), purpose="assistants")
            return key, file.id

        pending = [(food_id, body) for food_id, body in documents if sha256(food_id.encode()).hexdigest() not in uploads]
        for start in range(0, len(pending), 16):
            batch = await asyncio.gather(
                *(upload(food_id, body) for food_id, body in pending[start:start + 16]), return_exceptions=True,
            )
            for result in batch:
                if not isinstance(result, BaseException):
                    key, file_id = result
                    uploads[key] = file_id
            collection.update_one({"_id": build_id}, {"$set": {"uploads": uploads}})
            for result in batch:
                if isinstance(result, BaseException):
                    raise result
            print(f"Uploaded {len(uploads)}/{len(documents)} catalog files.", flush=True)

        files = [{"file_id": uploads[sha256(food_id.encode()).hexdigest()], "attributes": {"food_id": food_id}}
                 for food_id, _ in documents]
        attached = {file.id async for file in client.vector_stores.files.list(vector_store_id=store_id)}
        missing = [file for file in files if file["file_id"] not in attached]
        for start in range(0, len(missing), 500):
            await client.vector_stores.file_batches.create_and_poll(store_id, files=missing[start:start + 500])
        indexed = {file.id: file async for file in client.vector_stores.files.list(vector_store_id=store_id)}
        if any(file["file_id"] not in indexed or indexed[file["file_id"]].status != "completed"
               for file in files):
            raise RuntimeError("Some catalog files are still indexing or failed. The existing search index was preserved.")
        collection.replace_one(
            {"_id": ACTIVE_INDEX},
            {"_id": ACTIVE_INDEX, "revision": revision, "vector_store_id": store_id, "food_count": len(files)},
            upsert=True,
        )
        return store_id, len(files)


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pymongo import MongoClient

    load_dotenv()
    with MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000) as mongo:
        _, count = asyncio.run(build_index(mongo[os.getenv("MONGO_DATABASE") or "zippy"]))
        print(f"OpenAI indexed {count} MongoDB catalog dishes.")
