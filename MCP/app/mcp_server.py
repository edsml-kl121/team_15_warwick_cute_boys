"""MCP tools the agent uses. Payment approval is deliberately NOT a tool:
the agent can only request payment; the user approves with their PIN in the UI.
"""

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer

from app.store import DEMO_USER, PUBLIC_BASE_URL, store


mcp = MCPServer(
    name="shopee-sim",
    instructions=(
        "Simulated Shopee ecosystem (Shopee Food, Shopee Mall, ShopeePay) in Bangkok. "
        "Flow: search -> get_menu / search_products -> quote -> place_*_order -> request_payment. "
        "For a recommended dish, call find_similar_dishes, then ask the user: deliver it "
        "(quote_food_order -> place_food_order) or eat at the restaurant (give address, "
        "distance and phone so a table can be booked by call). "
        "You can NOT complete payment yourself: give the user the approve_url and wait for "
        "them to enter their ShopeePay PIN, then poll get_order_status. Prices are THB."
    ),
)


class FoodLine(BaseModel):
    item_id: str = Field(description="menu item id from get_menu, e.g. m_easy_health_1")
    qty: int = Field(1, ge=1, le=20)


class MallLine(BaseModel):
    product_id: str = Field(
        description="product id from search_products, e.g. p_eyemask"
    )
    qty: int = Field(1, ge=1, le=20)


def _dump(lines: list[BaseModel]) -> list[dict]:
    return [line.model_dump() for line in lines]


@mcp.tool()
def search_restaurants(
    query: str = "",
    lat: float | None = None,
    lng: float | None = None,
    max_km: float = 10,
) -> list[dict]:
    """Find Shopee Food restaurants near a location (defaults to Silom, Bangkok).
    query matches shop name, cuisine or dish names (e.g. 'salmon', 'healthy', 'thai').
    Returns address, phone (E.164, for booking calls), distance, delivery fee, ETA and
    price range, nearest first."""
    return store.search_restaurants(query, lat, lng, max_km)


@mcp.tool()
def find_similar_dishes(
    dish: str,
    calories: float | None = None,
    protein_g: float | None = None,
    lat: float | None = None,
    lng: float | None = None,
    max_km: float = 10,
    limit: int = 10,
) -> list[dict]:
    """Find menu items matching a recommended dish (e.g. from a nutrition recommender),
    best first. Matches on dish-name words; pass the recommended calories / protein_g to
    also rank by macro closeness and surface similar dishes when no name matches.
    Each hit has item_id, price, nutrition, match_score (0-1) and restaurant info
    (name, branch, address, phone, distance_km, delivery_fee_thb, eta_min)."""
    return store.find_similar_dishes(dish, calories, protein_g, lat, lng, max_km, limit)


@mcp.tool()
def get_menu(shop_id: str) -> dict:
    """Restaurant info (address, phone, location) plus full menu with price and nutrition
    (calories, protein, carbs, fat) per item."""
    return store.get_menu(shop_id)


@mcp.tool()
def quote_food_order(
    items: list[FoodLine], lat: float | None = None, lng: float | None = None
) -> dict:
    """Price check before ordering: subtotal, delivery fee, total, ETA and nutrition total.
    All items must be from one restaurant. Places nothing."""
    return store.quote_food(_dump(items), lat, lng)


@mcp.tool()
def place_food_order(
    items: list[FoodLine],
    note: str = "",
    lat: float | None = None,
    lng: float | None = None,
) -> dict:
    """Create a Shopee Food order in status pending_payment. Call request_payment next.
    Only do this after the user agreed to the dish and price."""
    return store.place_order("food", _dump(items), DEMO_USER, note, lat, lng)


@mcp.tool()
def search_products(query: str = "", category: str = "") -> list[dict]:
    """Search Shopee Mall products (categories: sleep, recovery).
    Try 'eye mask', 'gel eye pads', 'white noise', or 'yoga mat'.
    Several shops sell similar items (e.g. 4 eye masks, 59-390 THB): compare shop, price
    and rating, and let the user pick."""
    return store.search_products(query, category)


@mcp.tool()
def place_mall_order(items: list[MallLine]) -> dict:
    """Create a Shopee Mall order in status pending_payment (free shipping over 299 THB).
    Call request_payment next. Only after the user agreed."""
    return store.place_order("mall", _dump(items), DEMO_USER)


@mcp.tool()
def request_payment(order_id: str, return_url: str | None = None) -> dict:
    """Create a ShopeePay payment request for a pending order. Returns approve_url:
    send it to the user, who confirms with their PIN. You cannot approve it yourself.
    Optionally pass Zippy's configured return URL to go back after approval."""
    intent = store.create_payment_intent(order_id, return_url)
    return {**intent, "approve_url": f"{PUBLIC_BASE_URL}{intent['approve_path']}"}


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Live order status: pending_payment, cancelled, confirmed, preparing, rider_assigned,
    picked_up, delivered (food) or packed, shipped, delivered (mall)."""
    return store.view_order(order_id)


@mcp.tool()
def list_orders() -> list[dict]:
    """The user's orders, newest first. Useful as food history."""
    return store.list_orders(DEMO_USER)


@mcp.tool()
def cancel_order(order_id: str) -> dict:
    """Cancel an order that has not been paid yet."""
    return store.cancel_order(order_id)


@mcp.tool()
def get_wallet_balance() -> dict:
    """ShopeePay balance in THB, to check budget before suggesting an order."""
    return store.wallet(DEMO_USER)
