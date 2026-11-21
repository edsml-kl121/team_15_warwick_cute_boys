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

From the repository root, run `docker compose build backend` to verify the container. The build imports `main:app` from the packaged files before producing an image.

On Railway, set a separate shared `API_TOKEN` in Backend → Variables and give the frontend server the same value. Set `FRONTEND_ORIGIN` to the deployed frontend's origin. Use Railway's injected `PORT` and the backend image's default listen address. The local `.env` stays out of Git and the Docker image.

Use `DEMO_NOW` to set the starting clock in Bangkok. The default is 07:02 on 21 November 2026. The demo reset only cancels unpaid orders created in that run.

## Guest storage on Railway

Set the Backend variables below. MongoDB stays on the Railway private network.

```dotenv
MONGO_URL=${{MongoDB.MONGO_URL}}
MONGO_DATABASE=zippy
S3_BUCKET=${{bucket.BUCKET}}
S3_ENDPOINT_URL=${{bucket.ENDPOINT}}
S3_ADDRESSING_STYLE=virtual
AWS_REGION=${{bucket.REGION}}
AWS_ACCESS_KEY_ID=${{bucket.ACCESS_KEY_ID}}
AWS_SECRET_ACCESS_KEY=${{bucket.SECRET_ACCESS_KEY}}
```

Startup creates the collections and indexes idempotently and seeds the mock wellness day. To run the initializer separately from a machine with private database access, run `uv run python -m storage` from `BE/` with `MONGO_URL` configured.

| Collection | Contents |
| --- | --- |
| `guests` | Cookie-token hash, profile, preferences, goals, sharing choices, mock dataset reference and the optional imported `persona` health history |
| `wellness_days` | Versioned sample sleep, recovery and activity by date |
| `meals` | Guest-owned meal entries and optional food image keys |
| `sessions`, `session_events` | Guest-owned conversations, workflow state, completed turns, cards and feed events |
| `orders`, `bookings`, `reminders` | Guest-owned actions and their statuses |

Keep one Backend replica. Local runs without `MONGO_URL` use scoped JSON files under `DATA_DIR`. The visitor cookie lasts 90 days and restores a profile on the same browser. Open `/?demo=ploy` to start the scripted demo and use the presenter dashboard from that browser. Its reset applies to that Ploy run.

`PUT /persona` imports a visitor's own health history as one JSON document (`profile`, `food_history_log`, `wearable_daily`, `workouts`, `weights`, `body_composition_scans`). The backend validates it, stores it on the guest, applies the calorie and macro targets, name, area, tastes and connected sources to the profile, and merges that day's meals into `GET /food-log`. The coach's `get_health_history` tool returns a compact summary of it, never the raw log. `GET /persona` returns the stored document.

The bucket stores JPEG food images. MongoDB saves each image's object key, and the backend issues a fresh signed URL for display. Food photo analysis also requires `OPENAI_API_KEY`.

Calls simulate results by default. For live calls in the Ploy demo set `LIVE_CALLS=1`, the Twilio and OpenAI variables from the spec, and a comma-separated `TWILIO_VERIFIED_TEST_NUMBERS` list of team-owned numbers. The backend requires the listing number to match that list. An OpenAI key enables free-form chat through the Agents SDK.
