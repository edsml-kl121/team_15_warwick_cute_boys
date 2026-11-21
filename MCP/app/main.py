"""Shopee simulator: one process serving the MCP endpoint (/mcp), a REST API (/api)
and the human UI (/ for orders + wallet, /pay/{intent_id} for the ShopeePay PIN screen).
"""

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcp.server.transport_security import TransportSecuritySettings

from app.mcp_server import PUBLIC_BASE_URL, mcp
from app.store import DEMO_USER, SimError, store

log = logging.getLogger("shopee-sim")
STATIC = Path(__file__).parent / "static"
# Where delivered orders get announced (e.g. AI-HERE's food-log ingest). Unset = no webhook.
WEBHOOK_URL = os.getenv("DELIVERY_WEBHOOK_URL", "")
WEBHOOK_POLL_S = 2

# DNS-rebinding guard: accept localhost plus the public host we are deployed under.
_public = urlparse(PUBLIC_BASE_URL)
_security = TransportSecuritySettings(
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", _public.netloc, f"{_public.hostname}:*"],
    allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
                     f"{_public.scheme}://{_public.netloc}"],
)
# Served at exactly /mcp (Claude Code strips the trailing slash; a Mount would 307 to /mcp/).
mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", transport_security=_security)


async def deliver_webhooks() -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            await asyncio.sleep(WEBHOOK_POLL_S)
            for order in store.take_newly_delivered():
                log.info("order delivered: %s", order["order_id"])
                if not WEBHOOK_URL:
                    continue
                try:
                    resp = await client.post(
                        WEBHOOK_URL, json={"event": "order.delivered", "order": order}
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    # ponytail: no retry queue; delivery is demo-only. Add one if the receiver flakes.
                    log.warning("webhook failed for %s: %s", order["order_id"], exc)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(deliver_webhooks())
    try:
        async with mcp.session_manager.run():
            yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Shopee Simulator", lifespan=lifespan)
app.router.routes.extend(mcp_app.routes)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(SimError)
async def sim_error(_: Request, exc: SimError) -> JSONResponse:
    status = 404 if exc.code.endswith("_not_found") else 400
    return JSONResponse({"code": exc.code, "message": exc.message}, status_code=status)


# ---------- UI ----------


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/pay/{intent_id}", include_in_schema=False)
def pay_page(intent_id: str) -> FileResponse:
    return FileResponse(STATIC / "pay.html")


# ---------- REST (UI + non-MCP clients) ----------


class OrderIn(BaseModel):
    kind: str = "mall"
    items: list[dict]
    note: str = ""
    lat: float | None = None
    lng: float | None = None


class PaymentIn(BaseModel):
    return_url: str | None = None


class PinIn(BaseModel):
    pin: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "public_base_url": PUBLIC_BASE_URL}


@app.get("/api/restaurants")
def restaurants(
    query: str = "", lat: float | None = None, lng: float | None = None, max_km: float = 10
) -> list[dict]:
    return store.search_restaurants(query, lat, lng, max_km)


@app.get("/api/restaurants/{shop_id}/menu")
def menu(shop_id: str) -> dict:
    return store.get_menu(shop_id)


@app.get("/api/products")
def products(query: str = "", category: str = "") -> list[dict]:
    return store.search_products(query, category)


@app.post("/api/orders")
def create_order(body: OrderIn) -> dict:
    return store.place_order(body.kind, body.items, DEMO_USER, body.note, body.lat, body.lng)


@app.get("/api/orders")
def orders() -> list[dict]:
    return store.list_orders(DEMO_USER)


@app.get("/api/orders/{order_id}")
def order(order_id: str) -> dict:
    return store.view_order(order_id)


@app.post("/api/orders/{order_id}/pay")
def create_payment(order_id: str, body: PaymentIn | None = None) -> dict:
    intent = store.create_payment_intent(order_id, body.return_url if body else None)
    return {**intent, "approve_url": f"{PUBLIC_BASE_URL}{intent['approve_path']}"}


@app.get("/api/wallet")
def wallet() -> dict:
    return store.wallet(DEMO_USER)


@app.get("/api/payments/{intent_id}")
def payment(intent_id: str) -> dict:
    return store.get_payment(intent_id)


@app.post("/api/payments/{intent_id}/approve")
def approve(intent_id: str, body: PinIn) -> dict:
    return store.approve_payment(intent_id, body.pin)


@app.post("/api/payments/{intent_id}/decline")
def decline(intent_id: str) -> dict:
    return store.decline_payment(intent_id)
