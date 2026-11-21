"""Deployable Streamable HTTP MCP server for the Life with Zippy demo."""
import base64
import json
import os
import threading
import time
from urllib.request import Request as UrlRequest, urlopen

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from app.store import SimError, Store

base_url = os.getenv("PUBLIC_BASE_URL", f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}" if os.getenv("RAILWAY_PUBLIC_DOMAIN") else "").rstrip("/")
hosts = [h for h in ("localhost", "127.0.0.1", "[::1]", os.getenv("RAILWAY_PRIVATE_DOMAIN"), os.getenv("RAILWAY_PUBLIC_DOMAIN"), base_url.removeprefix("https://").removeprefix("http://")) if h]
authorities = [a for h in hosts for a in (h, f"{h}:*")]
mcp = FastMCP("Shopee simulator", stateless_http=True, json_response=True,
    instructions="Simulated Shopee Food, Mall, and ShopeePay. Request payments only; never approve them.",
    transport_security=TransportSecuritySettings(allowed_hosts=authorities, allowed_origins=[f"{scheme}://{a}" for scheme in ("http", "https") for a in authorities]))
store = Store(base_url=base_url)
delivered_webhooks = set()

def _delivery_webhook_loop():
    """Emit each delivered order once; delivery is best-effort by design."""
    while True:
        target = os.getenv("DELIVERY_WEBHOOK_URL")
        if target:
            for order in store.list_orders():
                if order["status"] == "delivered" and order["id"] not in delivered_webhooks:
                    delivered_webhooks.add(order["id"])
                    try:
                        payload = json.dumps({"event":"order.delivered", "order":order}).encode()
                        urlopen(UrlRequest(target, data=payload, headers={"content-type":"application/json"}, method="POST"), timeout=5).read()
                    except OSError:
                        pass
        time.sleep(2)

threading.Thread(target=_delivery_webhook_loop, daemon=True).start()

def _error(error: SimError):
    return JSONResponse({"error": error.code, "message": error.message}, status_code=404 if error.code.endswith("_not_found") else 400)

def _payment(intent):
    return intent | {"approve_url": f"{base_url or 'http://localhost:8090'}/pay/{intent['id']}"}

@mcp.tool()
def search_restaurants(query: str="", lat: float=13.7246, lng: float=100.5293, max_km: float=10):
    """Find nearby Bangkok restaurants, ordered nearest first."""; return store.search_restaurants(query, lat, lng, max_km)
@mcp.tool()
def find_similar_dishes(dish: str, calories: int|None=None, protein_g: int|None=None, lat: float=13.7246, lng: float=100.5293, max_km: float=10, limit: int=10):
    """Find menu items similar to a recommended meal."""; return store.find_similar_dishes(dish, calories, protein_g, lat, lng, max_km, limit)
@mcp.tool()
def get_menu(shop_id: str):
    """Get a restaurant and its full menu."""; return store.get_menu(shop_id)
@mcp.tool()
def quote_food_order(items: list[dict], lat: float=13.7246, lng: float=100.5293):
    """Calculate a food delivery total without placing an order."""; return store.quote_food_order(items, lat, lng)
@mcp.tool()
def place_food_order(items: list[dict], note: str="", lat: float=13.7246, lng: float=100.5293):
    """Create a food order awaiting human payment."""; return store.place_food_order(items, note, lat, lng)
@mcp.tool()
def search_products(query: str="", category: str|None=None):
    """Search simulated Shopee Mall products in sleep or recovery categories."""; return store.search_products(query, category)
@mcp.tool()
def place_mall_order(items: list[dict]):
    """Create a Mall order awaiting human payment."""; return store.place_mall_order(items)
@mcp.tool()
def request_payment(order_id: str, return_url: str|None=None):
    """Create a payment intent; approval only happens on the human payment page. Optionally redirect there after completion."""
    return _payment(store.request_payment(order_id, return_url))
@mcp.tool()
def get_order_status(order_id: str):
    """Get live order status."""; return store.get_order_status(order_id)
@mcp.tool()
def list_orders():
    """List orders newest first."""; return store.list_orders()
@mcp.tool()
def cancel_order(order_id: str):
    """Cancel an unpaid order."""; return store.cancel_order(order_id)
@mcp.tool()
def get_wallet_balance():
    """Get the simulated ShopeePay wallet balance."""; return store.get_wallet_balance()

@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request): return JSONResponse({"status":"ok", "public_base_url":base_url or "http://localhost:8090"})
@mcp.custom_route("/api/restaurants", methods=["GET"])
async def api_restaurants(_request: Request): return JSONResponse(store.search_restaurants())
@mcp.custom_route("/api/restaurants/{shop_id}/menu", methods=["GET"])
async def api_menu(request: Request):
    try: return JSONResponse(store.get_menu(request.path_params["shop_id"]))
    except SimError as error: return _error(error)
@mcp.custom_route("/api/products", methods=["GET"])
async def api_products(request: Request): return JSONResponse(store.search_products(request.query_params.get("query", ""), request.query_params.get("category")))
@mcp.custom_route("/api/orders", methods=["GET", "POST"])
async def api_orders(request: Request):
    try:
        if request.method == "GET": return JSONResponse(store.list_orders())
        body = await request.json()
        order = store.place_food_order(body["items"], body.get("note", ""), body.get("lat",13.7246), body.get("lng",100.5293)) if body.get("kind")=="food" else store.place_mall_order(body["items"])
        return JSONResponse(order, status_code=201)
    except SimError as error: return _error(error)
@mcp.custom_route("/api/orders/{order_id}", methods=["GET"])
async def api_order(request: Request):
    try: return JSONResponse(store.get_order_status(request.path_params["order_id"]))
    except SimError as error: return _error(error)
@mcp.custom_route("/api/orders/{order_id}/pay", methods=["POST"])
async def api_order_pay(request: Request):
    try:
        body = await request.json()
        return JSONResponse(_payment(store.request_payment(request.path_params["order_id"], body.get("return_url"))))
    except SimError as error: return _error(error)
@mcp.custom_route("/api/payments/{intent_id}", methods=["GET"])
async def api_payment(request: Request):
    try: return JSONResponse(_payment(store.get_payment(request.path_params["intent_id"])))
    except SimError as error: return _error(error)
@mcp.custom_route("/api/payments/{intent_id}/approve", methods=["POST"])
async def api_approve(request: Request):
    try: return JSONResponse(store.approve_payment(request.path_params["intent_id"], (await request.json()).get("pin", "")))
    except SimError as error: return _error(error)
@mcp.custom_route("/api/payments/{intent_id}/decline", methods=["POST"])
async def api_decline(request: Request):
    try: return JSONResponse(store.decline_payment(request.path_params["intent_id"]))
    except SimError as error: return _error(error)
@mcp.custom_route("/api/wallet", methods=["GET"])
async def api_wallet(_request: Request): return JSONResponse(store.get_wallet_balance())
@mcp.custom_route("/", methods=["GET"])
async def dashboard(_request: Request): return HTMLResponse("<h1>Shopee simulator</h1><p>Mock Mall, Food, and ShopeePay service.</p><p><a href='/health'>Health</a> · <a href='/api/orders'>Orders</a></p>")
@mcp.custom_route("/pay/{intent_id}", methods=["GET"])
async def pay_page(request: Request):
    iid=request.path_params["intent_id"]
    return HTMLResponse(f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{{margin:0;background:#f5f5f5;font:15px Arial;color:#333}}header{{padding:17px 24px;background:#ee4d2d;color:white;font-size:22px;font-weight:bold}}main{{max-width:430px;margin:38px auto;background:white;padding:28px;box-shadow:0 1px 4px #bbb}}.amount{{font-size:28px;font-weight:bold;margin:20px 0}}input,button{{box-sizing:border-box;width:100%;padding:14px;font-size:16px}}input{{border:1px solid #ddd;margin:14px 0}}button{{background:#ee4d2d;color:white;border:0;font-weight:bold;cursor:pointer}}small{{color:#777}}</style><header>🛍️ ShopeePay</header><main><small>Secure payment</small><h2>Confirm payment</h2><div class="amount" id="amount">Loading…</div><p>Enter your 6-digit ShopeePay PIN to approve.</p><input id="pin" type="password" inputmode="numeric" maxlength="6" placeholder="ShopeePay PIN" autofocus><button onclick="approve()">Pay now</button><p id="status"></p></main><script>let payment;fetch('/api/payments/{iid}').then(r=>r.json()).then(x=>{{payment=x;amount.textContent='฿'+x.amount_thb}});async function approve(){{let r=await fetch('/api/payments/{iid}/approve',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{pin:pin.value}})}});let x=await r.json();status.textContent=x.status==='approved'?'Payment successful! Redirecting…':x.status||x.message;if(x.status==='approved'&&payment.return_url){{let u=new URL(payment.return_url);u.searchParams.set('payment_status',x.status);u.searchParams.set('order_id',x.order_id);setTimeout(()=>location.href=u,900)}}}}</script>''')
@mcp.custom_route("/static/products/{product_id}.jpg", methods=["GET"])
async def product_image(_request: Request): return Response(b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;", media_type="image/gif")

app = mcp.streamable_http_app()
