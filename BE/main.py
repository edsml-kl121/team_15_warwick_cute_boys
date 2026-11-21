import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager, nullcontext
from datetime import date
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from demo import Clock, DEMO_DATE
from integrations import AgentsCoach, MealPhotos, Prompts, Shopee
from service import MOMENTS, Zippy
from storage import DemoHealth, JsonStore
from telephony import DemoPhone, RealtimeFactory, TwilioPhone, bridge

load_dotenv()
Moment = Literal["morning_sleep", "dinner_tip", "daily_summary"]


class Settings:
    def __init__(self):
        self.token = os.getenv("API_TOKEN", "" if os.getenv("RAILWAY_ENVIRONMENT") else "local-zippy")
        self.origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
        self.shopee_url = os.getenv("SHOPEE_MCP_URL", "https://shopee-sim-production.up.railway.app/mcp")
        self.directory = os.getenv("DATA_DIR", "./data")
        self.demo_now = os.getenv("DEMO_NOW", f"{DEMO_DATE}T07:02:00+07:00")
        self.use_ai = bool(os.getenv("OPENAI_API_KEY"))
        self.live_calls = os.getenv("LIVE_CALLS") == "1"


class SessionBody(BaseModel):
    session_id: str = Field(default="ploy", pattern=r"^[A-Za-z0-9_-]{1,80}$")


class ChatBody(SessionBody):
    message: str = Field(min_length=1, max_length=1500)


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
    budget_thb: int = Field(gt=0, le=10000)


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    location: str = Field(max_length=120)
    member_since: str = Field(max_length=60)
    goals: Goals
    preferences: Preferences
    connections: list[Connection] = Field(max_length=32)


def create_app(*, settings=None, shopee=None, clock=None, store=None, health=None,
               phone=None, realtime=None, photos=None, coach=None, prompts_path=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        if not settings.token:
            raise RuntimeError("Set API_TOKEN before starting the backend.")
        prompts = Prompts(prompts_path)
        local_clock = clock or Clock(settings.demo_now)
        adapter = shopee or Shopee(settings.shopee_url)
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
                )
        photo_reader = photos
        if photo_reader is None and settings.use_ai and os.getenv("S3_BUCKET"):
            photo_reader = MealPhotos(os.environ["S3_BUCKET"], os.getenv("AWS_REGION"))
        assistant = coach or (AgentsCoach(prompts) if settings.use_ai else None)
        zippy = Zippy(store or JsonStore(settings.directory, local_clock.now().date().isoformat()),
                      local_clock, health or DemoHealth(), adapter, prompts, assistant, telephony, photo_reader)
        app.state.zippy = zippy
        app.state.realtime = realtime or RealtimeFactory(
            prompts, os.getenv("REALTIME_MODEL", "gpt-realtime-2.1"), os.getenv("REALTIME_VOICE"),
            os.getenv("CALL_LANGUAGE", "English"),
            [code.strip() for code in os.getenv("TRANSCRIPTION_LANGUAGES", "en,th").split(",") if code.strip()],
        )

        async def reminders():
            while True:
                async with zippy.mutation:
                    zippy.due_reminders()
                await asyncio.sleep(5)

        async with adapter.connect() if hasattr(adapter, "connect") else nullcontext():
            zippy.spawn(reminders())
            try:
                yield
            finally:
                tasks = list(zippy.tasks)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Zippy", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[settings.origin], allow_methods=["GET", "POST", "PUT"],
                       allow_headers=["Authorization", "Content-Type"])

    async def auth(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization.encode(), f"Bearer {settings.token}".encode()):
            raise HTTPException(401, "Invalid API token.")

    def service(request: Request):
        return request.app.state.zippy

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

    @app.get("/profile", dependencies=protected)
    async def profile(zippy=Depends(service)):
        return zippy.state["profile"]

    @app.put("/profile", dependencies=protected)
    async def update_profile(body: Profile, zippy=Depends(service)):
        async with zippy.mutation:
            zippy.state["profile"] = body.model_dump()
            zippy.store.save()
            return zippy.state["profile"]

    @app.get("/today", dependencies=protected)
    async def today(zippy=Depends(service)):
        return zippy.today()

    @app.get("/food-log", dependencies=protected)
    async def food_log(date: date | None = None, zippy=Depends(service)):
        return zippy.food_log(date.isoformat() if date else zippy.state["date"])

    @app.post("/food-log/photo", dependencies=protected)
    async def photo(file: UploadFile = File(), session_id: str = "ploy", zippy=Depends(service)):
        if zippy.photos is None:
            raise HTTPException(503, "Meal photo analysis requires OpenAI and S3 configuration.")
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(415, "Choose an image.")
        image = await file.read(10 * 1024 * 1024 + 1)
        if len(image) > 10 * 1024 * 1024:
            raise HTTPException(413, "Choose an image under 10 MB.")
        snapshot = zippy.state
        try:
            estimate, url = await zippy.photos.read(image)
        except ValueError:
            raise
        except Exception:
            raise HTTPException(502, "Could not analyze the photo.") from None
        async with zippy.mutation:
            if snapshot is not zippy.state:
                raise HTTPException(409, "The demo was reset. Upload the photo again.")
            import uuid

            entry = {"id": uuid.uuid4().hex, "date": zippy.state["date"], "time": zippy.now().strftime("%H:%M"),
                     "meal": "Meal", "source": "photo", "photo_url": url, **estimate}
            zippy.state["food"].append(entry)
            zippy.emit(session_id, {"text": f"Meal logged from your photo: {entry['dish']}, about {entry['protein_g']} g protein."})
            return entry

    @app.post("/chat", dependencies=protected)
    async def chat(body: ChatBody, zippy=Depends(service)):
        async def events():
            async with zippy.chat_locks[body.session_id]:
                session = zippy.session(body.session_id)
                text = []
                try:
                    async for event in zippy.chat(body.session_id, body.message.strip()):
                        if event["type"] == "delta":
                            text.append(event["text"])
                        yield json.dumps(event, ensure_ascii=False) + "\n"
                    session["history"].extend([{"role": "user", "content": body.message},
                                               {"role": "assistant", "content": "".join(text)}])
                    zippy.store.save()
                    yield '{"type":"done"}\n'
                except Exception as error:
                    message = str(error) if isinstance(error, ValueError) else "Zippy couldn't complete that request. Try again."
                    yield json.dumps({"type": "error", "message": message}) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/feed", dependencies=protected)
    async def feed(session_id: str = "ploy", after: int = Query(default=0, ge=0), zippy=Depends(service)):
        return [item for item in zippy.session(session_id)["feed"] if item["id"] > after]

    @app.post("/actions/buy", dependencies=protected)
    async def buy(body: BuyBody, zippy=Depends(service)):
        return await zippy.buy(body.session_id, body.item_id)

    @app.post("/actions/pay", dependencies=protected)
    async def pay(body: OrderBody, zippy=Depends(service)):
        return await zippy.payment_url(body.session_id, body.order_id)

    @app.post("/actions/cancel", dependencies=protected)
    async def cancel(body: OrderBody, zippy=Depends(service)):
        return await zippy.order_status(body.session_id, body.order_id, cancel=True)

    @app.get("/shopee-orders/{order_id}", dependencies=protected)
    async def order_status(order_id: str, session_id: str = "ploy", zippy=Depends(service)):
        return await zippy.order_status(session_id, order_id)

    @app.get("/bookings/{booking_id}", dependencies=protected)
    async def booking_status(booking_id: str, session_id: str = "ploy", zippy=Depends(service)):
        booking = zippy.state["bookings"].get(booking_id)
        if not booking or booking["session_id"] != session_id:
            raise HTTPException(404, "Booking not found.")
        return {key: booking[key] for key in ("id", "status", "duration_s", "quote", "restaurant_name", "time")}

    @app.post("/proactive", dependencies=protected)
    async def proactive(body: ProactiveBody, zippy=Depends(service)):
        await zippy.proactive(body.moment, body.session_id)
        return {"status": "ok"}

    @app.post("/demo/trigger", dependencies=protected)
    async def trigger(body: TriggerBody, zippy=Depends(service)):
        if body.moment and not body.reminder:
            await zippy.proactive(body.moment, body.session_id, demo=True)
        elif body.reminder and not body.moment:
            async with zippy.mutation:
                zippy.state["clock"] = f'{zippy.state["date"]}T{body.reminder}:00+07:00'
                zippy.due_reminders(body.reminder)
                zippy.store.save()
        else:
            raise HTTPException(400, "Pass one moment or reminder.")
        return {"status": "ok"}

    @app.post("/demo/reset", dependencies=protected)
    async def reset(zippy=Depends(service)):
        if any(lock.locked() for lock in zippy.chat_locks.values()):
            raise HTTPException(409, "Wait for the current chat reply before resetting.")
        await zippy.reset()
        return {"status": "ok"}

    @app.post("/call-status")
    async def call_status(request: Request, booking_id: str, zippy=Depends(service)):
        phone = zippy.phone
        if not hasattr(phone, "validator"):
            raise HTTPException(403, "Twilio is disabled.")
        fields = await request.form()
        url = phone.public_url + "/call-status?" + request.url.query
        if not phone.validator.validate(url, fields, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403, "Invalid Twilio signature.")
        booking = zippy.state["bookings"].get(booking_id)
        if not booking or not fields.get("CallSid") or booking["call_sid"] not in (None, fields["CallSid"]):
            raise HTTPException(404, "Unknown call.")
        if fields.get("CallStatus") in {"no-answer", "busy", "failed"} or str(fields.get("AnsweredBy", "")).startswith("machine"):
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
        zippy = socket.app.state.zippy
        phone = zippy.phone
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
