# shopee-sim

Simulated Shopee Food / Shopee Mall / ShopeePay for the Zippy demo. The service
uses the catalog and UI from the standalone `shopee-sim` project at commit
`f45dea6`. One process serves:

- `/mcp` — MCP server (Streamable HTTP) for the agent
- `/` — live orders + wallet UI
- `/pay/{intent_id}` — ShopeePay PIN approval screen (human only)
- `/api/*` — REST used by the UI

The agent can search, quote, order and *request* payment. It can never approve:
only a person entering the PIN on `/pay/...` moves money.

## Run

```bash
uv sync --locked
uv run uvicorn app.main:app --port 8090
uv run --locked pytest -q
```

Env: `SIM_PIN` (default `123456`), `SIM_START_BALANCE` (1500), `SIM_SPEED` (1 = food delivered ~45s
after payment), `PUBLIC_BASE_URL` (for `approve_url`), `DELIVERY_WEBHOOK_URL` (POSTed
`{"event": "order.delivered", "order": ...}` once per delivered order), `SIM_DEMO_PHONE`
(E.164; replaces every restaurant phone so live booking calls reach your own number).

State is in memory and resets on restart.

Use the **Restaurants** tab on the dashboard to preview the catalog photos. The
restaurant search, menu, and dish-match responses include the same self-hosted
`image_url` and `image_credit`. Credits, source links, and licenses are recorded
in [restaurant_photos.json](app/data/restaurant_photos.json). Images were resized
for the demo and are cropped in the UI. Representative dish photos are labeled.

### Demo catalog

Shopee Food has 16 Bangkok restaurants and 96 menu entries. Items tagged
`price_source=simulated` have fixture prices and estimated nutrition. All
restaurant listings use the team demo phone by default. Try searching for
`boat noodles`, `crispy tofu riceberry bowl` or `honey toast`.

Shopee Mall has 15 sleep and recovery products. Try `gel eye pads`,
`white noise`, `yoga mat` or `resistance band`. The six new products have
original, AI-generated studio thumbnails in [app/static/products](app/static/products).
The prompts used a warm off-white background, a centered unbranded product,
soft daylight and no text for each of the eye pads, neck pillow, sound machine,
yoga mat, resistance bands and steel bottle.

Mall order lines carry the product thumbnail to the ShopeePay PIN screen.

From the repository root, `docker compose up --build mcp` serves the UI at
`http://localhost:8001/` and MCP at `http://localhost:8001/mcp`.

## Return to Zippy after payment

Set `SIM_RETURN_ORIGIN` to the Zippy frontend origin, for example
`http://localhost:3000`. Pass the full page URL as `return_url` to
`request_payment` and open the returned `approve_url`. After PIN approval,
**Back to Zippy** opens that page with
`payment_status=approved` and `order_id`, preserving the URL's other query
parameters and fragment. Confirm the order using `get_order_status` or the
backend status endpoint. With no return URL, the payment page shows a receipt.

## Deploy on Railway

Set the service root to `/MCP` and the Railway config file to
`/MCP/railway.json`. The Dockerfile installs the locked dependencies. Run one
replica and check `/health` for the expected `public_base_url`. The simulator
uses Railway's public domain automatically unless `PUBLIC_BASE_URL` is set.

## Connect an agent

```bash
claude mcp add --transport http shopee-sim http://localhost:8090/mcp
```

Tools: `search_restaurants`, `find_similar_dishes`, `get_menu`, `quote_food_order`, `place_food_order`, `search_products`,
`place_mall_order`, `request_payment`, `get_order_status`, `list_orders`, `cancel_order`,
`get_wallet_balance`.
