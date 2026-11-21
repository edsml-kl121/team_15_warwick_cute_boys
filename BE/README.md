# Zippy backend

The FastAPI backend streams chat, assembles cards from source data, and owns the feed, orders, booking calls and reminders.

## Run and verify

From `BE/`:

```sh
cp .env.example .env
uv sync
uv run pytest -q
uv run python -m main
curl -fsS http://localhost:8080/health
curl -fsS -H 'Authorization: Bearer local-zippy' http://localhost:8080/today
```

The example environment uses the team's hosted Shopee simulator. Set `SHOPEE_MCP_URL=http://localhost:8090/mcp` for your own local copy. Tests inject a fake and require no services. The local development token is `local-zippy`.

On Railway, set a separate shared `API_TOKEN` in Backend → Variables and give the frontend server the same value. Set `FRONTEND_ORIGIN` to the deployed frontend's origin. Use Railway's injected `PORT` and the backend image's default listen address. The local `.env` stays out of Git and the Docker image.

Use `DEMO_NOW` to set the starting clock in Bangkok. The default is 07:02 on 21 November 2026. A single replica and writable `DATA_DIR` are required. The demo reset only cancels unpaid orders created by this backend.

Calls simulate results by default. For live calls set `LIVE_CALLS=1`, the Twilio and OpenAI variables from the spec, and a comma-separated `TWILIO_VERIFIED_TEST_NUMBERS` list of team-owned numbers. The backend requires the listing number to match that list. Configure `S3_BUCKET`, `AWS_REGION` and AWS credentials to enable meal photos. An OpenAI key enables free-form chat through the Agents SDK.
