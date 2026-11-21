import asyncio
import json
import os
import re
import secrets
import uuid
from contextlib import aclosing, asynccontextmanager, nullcontext
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Annotated, Literal

from anyio import CancelScope
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints

from demo import Clock
from integrations import AgentsCoach, BucketImages, MealPhotos, Prompts, Shopee, bucket_client
from persona import Persona, apply_to_profile
from push import WebPush, add_subscription
from recommendations import BucketRecommendationData, RecommendationAgents, RecommendationUnavailable
from service import MOMENTS, Zippy
from storage import DemoHealth, JsonStore, VisitorStores, initialize_mongo
from telephony import DemoPhone, RealtimeFactory, TwilioPhone, bridge

load_dotenv()
Moment = Literal["morning_sleep", "dinner_tip", "daily_summary", "weekly_recap"]
SESSION_ID = r"^[A-Za-z0-9_-]{1,80}$"
SessionQuery = Annotated[str, Query(pattern=SESSION_ID)]


class Settings:
    def __init__(self):
        self.token = os.getenv("API_TOKEN", "" if os.getenv("RAILWAY_ENVIRONMENT") else "local-zippy")
        self.origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
        self.shopee_url = os.getenv("SHOPEE_MCP_URL", "https://shopee-sim-production.up.railway.app/mcp")
        self.directory = os.getenv("DATA_DIR", "./data")
        self.demo_now = os.getenv("DEMO_NOW") or None  # unset: real Bangkok time; set to pin the clock
        self.use_ai = bool(os.getenv("OPENAI_API_KEY"))
        self.live_calls = os.getenv("LIVE_CALLS") == "1"
        self.mongo_url = os.getenv("MONGO_URL")
        self.mongo_database = os.getenv("MONGO_DATABASE") or "zippy"
        self.recommendation_mongo_url = os.getenv("RECOMMENDATION_MONGO_URL")
        self.secure_cookies = bool(os.getenv("RAILWAY_ENVIRONMENT"))
        self.vapid_public_key = os.getenv("VAPID_PUBLIC_KEY", "")
        self.vapid_private_key = os.getenv("VAPID_PRIVATE_KEY", "")
        self.vapid_subject = os.getenv("VAPID_SUBJECT", "mailto:zippy@example.com")
        # Presenter routes act on any guest by name, so they need their own secret on Railway.
        self.presenter_key = os.getenv("PRESENTER_KEY", "" if os.getenv("RAILWAY_ENVIRONMENT") else "local-presenter")


class SessionBody(BaseModel):
    session_id: str = Field(default="ploy", pattern=SESSION_ID)


class ChatBody(SessionBody):
    message: str = Field(min_length=1, max_length=1500)
    # The browser's current position, sent when the visitor allows location access.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class BuyBody(SessionBody):
    item_id: str = Field(min_length=1, max_length=100)


class OrderBody(SessionBody):
    order_id: str = Field(min_length=1, max_length=100)


class ProactiveBody(SessionBody):
    moment: Moment


class TriggerBody(SessionBody):
    moment: Moment | None = None
    reminder: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


class Connection(BaseModel):
    app: str = Field(min_length=1, max_length=60)
    connected: bool
    shares: list[str] = Field(max_length=12)


class Goals(BaseModel):
    sleep_minutes: int = Field(gt=0, le=1440)
    deep_minutes: int = Field(gt=0, le=1440)
    protein_g: int = Field(gt=0, le=999)
    kcal: int = Field(gt=0, le=9999)
    active_minutes: int = Field(gt=0, le=1440)
    steps: int = Field(gt=0, le=100000)
    carbs_g: int = Field(gt=0, le=999)
    fat_g: int = Field(gt=0, le=999)


class Preferences(BaseModel):
    food: str = Field(max_length=240)
    home: str = Field(max_length=240)
    work: str = Field(max_length=240)


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    location: str = Field(max_length=120)
    member_since: str = Field(max_length=60)
    goals: Goals
    preferences: Preferences
    connections: list[Connection] = Field(max_length=32)


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushSubscription(BaseModel):
    endpoint: str = Field(pattern=r"^https://", max_length=1000)
    expirationTime: int | None = None
    keys: PushKeys


class SubscribeBody(SessionBody):
    subscription: PushSubscription


class PresenterTrigger(BaseModel):
    guest_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    moment: Moment | None = None
    reminder: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    agent: Literal["food", "item"] | None = None


class Onboarding(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    food: Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)] = ""


def visitor_mode(request):
    return request.headers.get("X-Zippy-Demo") == "1"


def visitor_cookie(demo):
    return "zippy_ploy" if demo else "zippy_guest"


def visitor_id(request, demo):
    token = request.cookies.get(visitor_cookie(demo), "")
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return ("demo-" if demo else "guest-") + sha256(token.encode()).hexdigest()
    return None


def create_app(*, settings=None, shopee=None, clock=None, store=None, health=None,
               phone=None, realtime=None, photos=None, coach=None, prompts_path=None, database=None, push=None,
               recommendation_data=None, images=None):
    settings = settings or Settings()
    push_sender = push or (WebPush(settings.vapid_public_key, settings.vapid_private_key, settings.vapid_subject)
                           if settings.vapid_public_key and settings.vapid_private_key else None)

    @asynccontextmanager
    async def lifespan(app):
        if not settings.token:
            raise RuntimeError("Set API_TOKEN before starting the backend.")
        prompts = Prompts(prompts_path)
        local_clock = clock or Clock(settings.demo_now)
        adapter = shopee or Shopee(settings.shopee_url)
        voice_agents = realtime or RealtimeFactory(
            prompts, os.getenv("REALTIME_MODEL", "gpt-realtime-2.1"), os.getenv("REALTIME_VOICE"),
            os.getenv("CALL_LANGUAGE", "English"),
            [code.strip() for code in os.getenv("TRANSCRIPTION_LANGUAGES", "en").split(",") if code.strip()],
        )
        telephony = phone
        if telephony is None:
            telephony = DemoPhone()
            if settings.live_calls:
                if not settings.use_ai:
                    raise ValueError("Live calls require OPENAI_API_KEY.")
                telephony = TwilioPhone(
                    os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"),
                    os.getenv("TWILIO_PHONE_NUMBER"), os.getenv("TWILIO_PUBLIC_BASE_URL"),
                    {number.strip() for number in os.getenv("TWILIO_VERIFIED_TEST_NUMBERS", "").split(",") if number.strip()},
                    int(os.getenv("RING_TIMEOUT_SECONDS", "40")), int(os.getenv("MAX_CALL_SECONDS", "300")),
                    realtime=voice_agents,
                )
        photo_reader = photos
        if photo_reader is None and settings.use_ai:
            photo_reader = MealPhotos(os.getenv("S3_BUCKET"), os.getenv("AWS_REGION"),
                                      os.getenv("S3_ENDPOINT_URL"), os.getenv("S3_ADDRESSING_STYLE", "auto"),
                                      os.getenv("FOOD_SCAN_MODEL") or "gpt-4.1-mini")
        assistant = coach or (AgentsCoach(prompts) if settings.use_ai else None)
        data = recommendation_data
        if data is None and (bucket := os.getenv("RECOMMENDATION_BUCKET") or os.getenv("S3_BUCKET")):
            client = getattr(photo_reader, "client", None) if bucket == os.getenv("S3_BUCKET") else None
            data = BucketRecommendationData(client, bucket) if client else BucketRecommendationData.connect(
                bucket, os.getenv("AWS_REGION"), os.getenv("S3_ENDPOINT_URL"), os.getenv("S3_ADDRESSING_STYLE", "auto"),
            )
        menu_images = images or (BucketImages(os.environ["S3_BUCKET"], bucket_client(
            os.getenv("AWS_REGION"), os.getenv("S3_ENDPOINT_URL"), os.getenv("S3_ADDRESSING_STYLE", "auto"),
        )) if os.getenv("S3_BUCKET") else None)
        demo_date = local_clock.now().date().isoformat()
        mongo_client = None
        db = database
        if db is None and settings.mongo_url:
            from pymongo import MongoClient

            mongo_client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=5000, timeoutMS=5000)
            db = mongo_client[settings.mongo_database]
        if db is not None:
            try:
                initialize_mongo(db, demo_date)
            except Exception:
                if mongo_client:
                    mongo_client.close()
                raise
        recommendation_client = None
        recommendation_db = None
        if settings.recommendation_mongo_url:
            from pymongo import MongoClient

            recommendation_client = MongoClient(settings.recommendation_mongo_url,
                                                serverSelectionTimeoutMS=5000, timeoutMS=5000)
            recommendation_db = recommendation_client[settings.mongo_database]
        app.state.recommendations = RecommendationAgents(
            data, prompts, (os.getenv("RECOMMENDATION_MODEL") or "gpt-4.1-mini") if settings.use_ai else None,
            database=recommendation_db,
        )
        stores = VisitorStores(settings.directory, demo_date, db)
        visitors = {}

        def build(guest_store, demo):
            return Zippy(guest_store, local_clock, health or DemoHealth(), adapter, prompts,
                         assistant, telephony if demo else DemoPhone(), photo_reader, push_sender, menu_images)

        def open_visitor(owner, *, demo, profile=None, create=False):
            if owner and owner not in visitors:
                guest_store = stores.open(owner, demo=demo, profile=profile, create=create)
                if guest_store is not None:
                    visitors[owner] = build(guest_store, demo)
            return visitors.get(owner)

        default_store = store or (stores.open("scheduled-demo", demo=True, create=True) if db is not None
                                  else JsonStore(settings.directory, demo_date))
        zippy = build(default_store, True)
        app.state.zippy = zippy
        app.state.open_visitor = open_visitor
        app.state.find_guests = stores.find_owners

        def booking_service(booking_id):
            if booking_id in zippy.state["bookings"]:
                return zippy
            for scoped in visitors.values():
                if booking_id in scoped.state["bookings"]:
                    return scoped
            owner = stores.booking_owner(booking_id)
            if owner:
                return open_visitor(owner, demo=owner.startswith("demo-"))
            return None

        app.state.booking_service = booking_service
        app.state.realtime = voice_agents

        async def reminders():
            while True:
                for scoped in (zippy, *visitors.values()):
                    async with scoped.mutation:
                        scoped.due_reminders()
                await asyncio.sleep(5)

        try:
            async with adapter.connect() if hasattr(adapter, "connect") else nullcontext():
                zippy.spawn(reminders())
                try:
                    yield
                finally:
                    tasks = [task for scoped in (zippy, *visitors.values()) for task in scoped.tasks]
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if recommendation_client:
                recommendation_client.close()
            if mongo_client:
                mongo_client.close()

    app = FastAPI(title="Zippy", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[settings.origin], allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Zippy-Demo", "X-Presenter-Key"])

    async def auth(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization.encode(), f"Bearer {settings.token}".encode()):
            raise HTTPException(401, "Invalid API token.")

    async def service(request: Request):
        demo = visitor_mode(request)
        zippy = request.app.state.open_visitor(visitor_id(request, demo), demo=demo)
        if zippy is None:
            raise HTTPException(401, "Start a guest session first.")
        return zippy

    def presenter(zippy=Depends(service)):
        if not zippy.store.demo:
            raise HTTPException(403, "Open the Ploy demo to use presenter controls.")
        return zippy

    @app.exception_handler(ValueError)
    async def invalid(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(LookupError)
    async def not_found(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.get("/health")
    @app.head("/health", include_in_schema=False)
    async def healthcheck():
        return {"status": "ok"}

    protected = [Depends(auth)]

    @app.get("/visitor", dependencies=protected)
    async def get_visitor(request: Request):
        demo = visitor_mode(request)
        zippy = request.app.state.open_visitor(visitor_id(request, demo), demo=demo)
        return {"ready": zippy is not None}

    @app.delete("/visitor", dependencies=protected)
    async def leave_visitor(request: Request, response: Response):
        response.delete_cookie(
            visitor_cookie(visitor_mode(request)), httponly=True, samesite="lax",
            secure=settings.secure_cookies or request.url.scheme == "https",
        )
        return {"ready": False}

    @app.post("/visitor", dependencies=protected)
    async def start_visitor(request: Request, response: Response, body: Onboarding | None = None):
        demo = visitor_mode(request)
        if request.app.state.open_visitor(visitor_id(request, demo), demo=demo):
            return {"ready": True}
        if not demo and body is None:
            raise HTTPException(422, "Enter a name to start.")
        profile = None
        if not demo:
            profile = {
                "name": body.name, "location": "", "connections": [],
                "member_since": datetime.now(timezone.utc).strftime("%b %Y"),
                "preferences": {"food": body.food, "home": "", "work": ""},
            }
        token = secrets.token_urlsafe(32)
        owner = ("demo-" if demo else "guest-") + sha256(token.encode()).hexdigest()
        request.app.state.open_visitor(owner, demo=demo, profile=profile, create=True)
        response.set_cookie(visitor_cookie(demo), token, httponly=True, samesite="lax",
                            secure=settings.secure_cookies or request.url.scheme == "https", max_age=60 * 60 * 24 * 90)
        return {"ready": True}

    @app.get("/sessions", dependencies=protected)
    async def sessions(zippy=Depends(service)):
        return sorted([
            {"id": session_id, "updated_at": session["updated_at"],
             "title": next((item["message"][:140] for item in session["timeline"] if item["type"] == "turn"), "Chat")}
            for session_id, session in zippy.state["sessions"].items() if session.get("timeline")
        ], key=lambda session: session["updated_at"], reverse=True)

    @app.get("/sessions/{session_id}", dependencies=protected)
    async def conversation(session_id: str, zippy=Depends(service)):
        session = zippy.state["sessions"].get(session_id)
        if session is None or not re.fullmatch(SESSION_ID, session_id):
            raise HTTPException(404, "Conversation not found.")
        return {"timeline": session.get("timeline", []), "last_feed_id": len(session["feed"])}

    @app.get("/profile", dependencies=protected)
    async def profile(zippy=Depends(service)):
        return zippy.state["profile"]

    @app.put("/profile", dependencies=protected)
    async def update_profile(body: Profile, zippy=Depends(service)):
        async with zippy.mutation:
            zippy.state["profile"] = body.model_dump()
            zippy.store.save()
            return zippy.state["profile"]

    @app.get("/persona", dependencies=protected)
    async def get_persona(zippy=Depends(service)):
        persona = zippy.state.get("persona")
        if persona is None:
            raise HTTPException(404, "No health data imported yet.")
        return persona

    @app.put("/persona", dependencies=protected)
    async def put_persona(body: Persona, zippy=Depends(service)):
        persona = body.model_dump(mode="json")
        async with zippy.mutation:
            zippy.state["persona"] = persona
            zippy.state["profile"] = apply_to_profile(zippy.state["profile"], persona)
            zippy.store.save()
        return {"persona_id": persona["profile"]["persona_id"], "meals": len(persona["food_history_log"]),
                "profile": zippy.state["profile"]}

    @app.get("/today", dependencies=protected)
    async def today(zippy=Depends(service)):
        return zippy.today()

    @app.get("/food-log", dependencies=protected)
    async def food_log(date: date | None = None, zippy=Depends(service)):
        result = zippy.food_log(date.isoformat() if date else zippy.state["date"])
        result["meals"] = [public_meal(meal, zippy.photos) for meal in result["meals"]]
        return result

    @app.get("/food-log/catalog-image", dependencies=protected)
    async def catalog_image(request: Request, food_id: str = Query(default="", max_length=128),
                            dish: str = Query(default="", max_length=240)):
        # Image elements send the visitor cookie but no app-specific demo header.
        if not any(request.app.state.open_visitor(visitor_id(request, demo), demo=demo) for demo in (False, True)):
            raise HTTPException(401, "Start a guest session first.")
        data = request.app.state.recommendations.data
        try:
            url = await data.catalog_image_url(food_id, dish) if data and (food_id or dish) else None
        except RecommendationUnavailable as error:
            raise HTTPException(503, str(error)) from None
        if not url:
            raise HTTPException(404, "Catalog image not found.")
        return RedirectResponse(url, headers={"Cache-Control": "no-store"})

    def public_meal(meal, photos):
        result = meal.copy()
        key = result.pop("photo_key", None)
        if key and photos:
            url = photos.url(key)
            if url:
                result["photo_url"] = url
        return result

    async def scan_meal(zippy, session_id, image):
        snapshot = zippy.state
        entry_id = uuid.uuid4().hex
        key = f"meals/{entry_id}.jpg"
        yield {"type": "progress", "stage": "analyzing"}
        try:
            estimate = await zippy.photos.read(image, key)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except Exception:
            raise HTTPException(502, "Couldn’t analyze the photo. Try again in a moment.") from None
        saved = False
        try:
            yield {"type": "progress", "stage": "saving"}
            async with zippy.mutation:
                if snapshot is not zippy.state:
                    raise HTTPException(409, "The demo was reset. Upload the photo again.")
                entry = {"id": entry_id, "date": zippy.state["date"], "time": zippy.now().strftime("%H:%M"),
                         "meal": "Meal", "source": "photo", "photo_key": key, **estimate}
                public = public_meal(entry, zippy.photos)
                if "photo_url" not in public:
                    entry.pop("photo_key")
                zippy.state["food"].append(entry)
                # The store may have written the meal if saving the feed entry fails.
                saved = True
                zippy.emit(session_id, {"text": f"Logged {entry['dish']} from your photo. About "
                                               f"{entry['kcal']} kcal and {entry['protein_g']} g protein."})
            yield {"type": "done", "meal": public}
        finally:
            if not saved:
                with CancelScope(shield=True):
                    await zippy.photos.discard(key)

    @app.post("/food-log/photo", dependencies=protected)
    async def photo(file: UploadFile = File(), session_id: SessionQuery = "ploy", stream: bool = False,
                    zippy=Depends(service)):
        if zippy.photos is None:
            raise HTTPException(503, "Meal photo analysis requires an OpenAI API key.")
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(415, "Choose an image.")
        limit = 10 * 1024 * 1024
        image = await file.read(limit + 1)
        if not image:
            raise HTTPException(400, "Choose a nonempty photo.")
        if len(image) > limit:
            raise HTTPException(413, "Choose an image under 10 MB.")

        if not stream:
            async with aclosing(scan_meal(zippy, session_id, image)) as scan:
                async for event in scan:
                    if event["type"] == "done":
                        return event["meal"]

        async def events():
            try:
                async with aclosing(scan_meal(zippy, session_id, image)) as scan:
                    async for event in scan:
                        yield json.dumps(event, ensure_ascii=False) + "\n"
            except HTTPException as error:
                yield json.dumps({"type": "error", "message": error.detail}) + "\n"
            except Exception:
                yield json.dumps({"type": "error", "message": "Couldn’t finish saving. Check your Food log before retrying."}) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})

    @app.post("/chat", dependencies=protected)
    async def chat(body: ChatBody, zippy=Depends(service)):
        message = body.message.strip()
        if not message:
            raise HTTPException(422, "Enter a message first.")

        async def events():
            async with zippy.chat_locks[body.session_id]:
                session = zippy.session(body.session_id)
                if body.lat is not None and body.lng is not None:
                    zippy.state["location"] = {"lat": body.lat, "lng": body.lng}
                recorded = []
                try:
                    async for event in zippy.chat(body.session_id, message):
                        if event["type"] == "delta" and recorded and recorded[-1]["type"] == "delta":
                            recorded[-1]["text"] += event["text"]
                        else:
                            recorded.append(event.copy())
                        yield json.dumps(event, ensure_ascii=False) + "\n"
                    async with zippy.mutation:
                        text = "".join(item["text"] for item in recorded if item["type"] == "delta")
                        session["history"].extend([{"role": "user", "content": message},
                                                   {"role": "assistant", "content": text}])
                        zippy.record_event(session, type="turn", message=message, events=recorded)
                        zippy.store.save()
                    yield '{"type":"done"}\n'
                except Exception as error:
                    detail = str(error) if isinstance(error, ValueError) else "Zippy couldn't complete that request. Try again."
                    yield json.dumps({"type": "error", "message": detail}) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/feed", dependencies=protected)
    async def feed(session_id: SessionQuery = "ploy", after: int = Query(default=0, ge=0), zippy=Depends(service)):
        return [item for item in zippy.state["sessions"].get(session_id, {}).get("feed", []) if item["id"] > after]

    @app.post("/actions/buy", dependencies=protected)
    async def buy(body: BuyBody, zippy=Depends(service)):
        return await zippy.buy(body.session_id, body.item_id)

    @app.post("/actions/pay", dependencies=protected)
    async def pay(body: OrderBody, request: Request, zippy=Depends(service)):
        demo_query = "?demo=ploy" if visitor_mode(request) else ""
        return_url = f"{settings.origin.rstrip('/')}/{demo_query}"
        return await zippy.payment_url(body.session_id, body.order_id, return_url=return_url)

    @app.post("/actions/cancel", dependencies=protected)
    async def cancel(body: OrderBody, zippy=Depends(service)):
        return await zippy.order_status(body.session_id, body.order_id, cancel=True)

    @app.get("/shopee-orders/{order_id}", dependencies=protected)
    async def order_status(order_id: str, session_id: SessionQuery = "ploy", zippy=Depends(service)):
        return await zippy.order_status(session_id, order_id)

    @app.get("/bookings/{booking_id}", dependencies=protected)
    async def booking_status(booking_id: str, session_id: SessionQuery = "ploy", zippy=Depends(service)):
        booking = zippy.state["bookings"].get(booking_id)
        if not booking or booking["session_id"] != session_id:
            raise HTTPException(404, "Booking not found.")
        return {key: booking[key] for key in ("id", "status", "duration_s", "quote", "restaurant_name", "time")}

    @app.post("/proactive", dependencies=protected)
    async def proactive(body: ProactiveBody, request: Request):
        zippy = request.app.state.zippy
        await zippy.proactive(body.moment, body.session_id)
        return {"status": "ok"}

    async def fire(zippy, session_id, moment, reminder):
        if moment and not reminder:
            await zippy.proactive(moment, session_id, demo=True, resend=True)
        elif reminder and not moment:
            async with zippy.mutation:
                zippy.state["clock"] = f'{zippy.state["date"]}T{reminder}:00+07:00'
                zippy.due_reminders(reminder)
                zippy.store.save()
        else:
            raise HTTPException(400, "Pass one moment or reminder.")

    @app.post("/demo/trigger", dependencies=protected)
    async def trigger(body: TriggerBody, zippy=Depends(presenter)):
        await fire(zippy, body.session_id, body.moment, body.reminder)
        return {"status": "ok"}

    @app.post("/presenter/trigger", dependencies=protected)
    async def presenter_trigger(request: Request, body: PresenterTrigger,
                                x_presenter_key: str = Header(default="")):
        """Trigger the requested action for all guests matching the display name."""
        if not settings.presenter_key or not secrets.compare_digest(x_presenter_key.encode(), settings.presenter_key.encode()):
            raise HTTPException(403, "Enter the presenter key.")
        if sum(value is not None for value in (body.agent, body.moment, body.reminder)) != 1:
            raise HTTPException(400, "Pass one agent, moment or reminder.")
        owners = request.app.state.find_guests(body.guest_name)
        if not owners:
            raise HTTPException(404, f"No guest named {body.guest_name}.")

        async def trigger_guest(owner):
            zippy = request.app.state.open_visitor(owner, demo=owner.startswith("demo-"))
            if zippy is None:
                raise HTTPException(404, f"No guest named {body.guest_name}.")
            sessions = zippy.state["sessions"]
            session_id = max(sessions, key=lambda key: sessions[key].get("updated_at") or "", default="presenter")
            if body.agent:
                try:
                    await zippy.recommend(request.app.state.recommendations, body.agent, session_id)
                except RecommendationUnavailable as error:
                    raise HTTPException(503, str(error)) from None
            else:
                await fire(zippy, session_id, body.moment, body.reminder)
            return session_id, len(zippy.state.get("push_subscriptions", []))

        results = await asyncio.gather(*(trigger_guest(owner) for owner in owners), return_exceptions=True)
        succeeded = [result for result in results if isinstance(result, tuple)]
        if not succeeded:
            raise results[0]
        response = {"status": "ok" if len(succeeded) == len(owners) else "partial",
                    "guests": len(succeeded), "matched_guests": len(owners),
                    "devices": sum(count for _, count in succeeded)}
        if len(owners) == 1:
            response["session_id"] = succeeded[0][0]
        return response

    @app.get("/push/key", dependencies=protected)
    async def push_key():
        if push_sender is None:
            raise HTTPException(503, "Push notifications aren't configured on the server.")
        return {"public_key": push_sender.public_key}

    @app.post("/push/subscribe", dependencies=protected)
    async def push_subscribe(body: SubscribeBody, zippy=Depends(service)):
        async with zippy.mutation:
            zippy.state["push_subscriptions"] = add_subscription(
                zippy.state.get("push_subscriptions", []), body.subscription.model_dump(exclude_none=True))
            zippy.store.save()
        return {"devices": len(zippy.state["push_subscriptions"])}

    @app.post("/demo/reset", dependencies=protected)
    async def reset(zippy=Depends(presenter)):
        if any(lock.locked() for lock in zippy.chat_locks.values()):
            raise HTTPException(409, "Wait for the current chat reply before resetting.")
        await zippy.reset()
        return {"status": "ok"}

    async def twilio_callback(request, path, booking_id):
        phone = request.app.state.zippy.phone
        if not hasattr(phone, "validator"):
            raise HTTPException(403, "Twilio is disabled.")
        fields = await request.form()
        url = phone.public_url + path + "?" + request.url.query
        if not phone.validator.validate(url, fields, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403, "Invalid Twilio signature.")
        zippy = request.app.state.booking_service(booking_id)
        booking = zippy.state["bookings"].get(booking_id) if zippy else None
        if not booking or not fields.get("CallSid") or booking["call_sid"] not in (None, fields["CallSid"]):
            raise HTTPException(404, "Unknown call.")
        return phone, zippy, booking, fields

    @app.post("/call-amd")
    async def call_amd(request: Request, booking_id: str):
        phone, zippy, booking, fields = await twilio_callback(request, "/call-amd", booking_id)
        booking["answered_by"] = str(fields.get("AnsweredBy", ""))
        zippy.store.save()
        if booking["answered_by"].startswith("machine") or booking["answered_by"] == "fax":
            await phone.hang_up(fields["CallSid"])
        return {"status": "ok"}

    @app.post("/call-status")
    async def call_status(request: Request, booking_id: str):
        _, zippy, booking, fields = await twilio_callback(request, "/call-status", booking_id)
        answered_by = str(fields.get("AnsweredBy") or booking.get("answered_by", ""))
        if fields.get("CallStatus") in {"no-answer", "busy", "failed"} or answered_by.startswith("machine") or answered_by == "fax":
            status = "no_answer"
        else:
            status = booking.get("result")
            status = status if status in {"booked", "full"} else "failed"
        duration = str(fields.get("CallDuration", ""))
        await zippy.finish_call(booking_id, status, int(duration) if duration.isdigit() else None)
        return {"status": "ok"}

    @app.websocket("/media-stream")
    @app.websocket("/media-stream/")
    async def media_stream(socket: WebSocket):
        phone = socket.app.state.zippy.phone
        signature = socket.headers.get("X-Twilio-Signature", "")
        if not hasattr(phone, "validator") or not any(
            phone.validator.validate(url, {}, signature) for url in (phone.media_url, phone.media_url + "/")
        ):
            await socket.close(code=1008)
            return
        await socket.accept()
        booking = None
        try:
            async with asyncio.timeout(10):
                while (packet := await socket.receive_json()).get("event") != "start":
                    if packet.get("event") != "connected":
                        await socket.close(code=1008)
                        return
            start = packet["start"]
            params = start["customParameters"]
            zippy = socket.app.state.booking_service(params.get("booking_id"))
            if zippy is None:
                await socket.close(code=1008)
                return
            booking = zippy.state["bookings"].get(params.get("booking_id"))
            if not booking or params.get("purpose") != "book_table" or booking["status"] != "calling" or booking["call_sid"] not in (None, start["callSid"]):
                await socket.close(code=1008)
                return
            booking["call_sid"] = start["callSid"]
            await bridge(socket, zippy, socket.app.state.realtime, booking, start)
        except (WebSocketDisconnect, TimeoutError):
            return
        except Exception:
            if booking:
                try:
                    await phone.hang_up(booking["call_sid"])
                finally:
                    await zippy.finish_call(booking["id"], "failed")
        finally:
            try:
                await socket.close()
            except (RuntimeError, WebSocketDisconnect):
                pass

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), ws_max_size=65536)
