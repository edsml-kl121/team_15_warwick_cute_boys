# Shopee simulator MCP

Mock Shopee Food, Shopee Mall, and ShopeePay service for the **Life with Zippy** demo. It is entirely in-memory and must run as one replica.

## Run locally

```bash
uv sync
uv run uvicorn server:app --host 0.0.0.0 --port 8090
uv run pytest
```

Connect an MCP client at `http://localhost:8090/mcp`. The server exposes 12 tools for restaurant/product search, quoting and placing orders, payment requests, order status, cancellation, and wallet balance. It intentionally has no MCP payment-approval tool.

## Payment redirect

Pass an optional `return_url` to `request_payment`. The returned `approve_url` opens a ShopeePay-styled human PIN page. On a successful PIN approval, it redirects to the supplied URL and adds `payment_status=approved` and `order_id=...` query parameters.

The default PIN is `123456`; wallet balance starts at 1,500 THB. Three incorrect PIN attempts decline the intent.

## Railway

Deploy the `MCP/` directory with its `Dockerfile`. Railway supplies `PORT` and automatically uses `https://$RAILWAY_PUBLIC_DOMAIN` for approval URLs. Set `PUBLIC_BASE_URL=https://<your-domain>` only when using a custom domain. The container starts `server:app` and serves its health check at `/health`.

```bash
curl https://<your-domain>/health
codex mcp add shopee-sim --url https://<your-domain>/mcp
```

Keep one replica: orders, payment intents, and wallet state are process memory.
