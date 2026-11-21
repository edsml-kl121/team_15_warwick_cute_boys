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

Set `OPENAI_API_KEY` to enable meal scanning. Each scan sends a resized JPG to one vision model using the Responses API and saves the estimated foods, portions and totals. The default `FOOD_SCAN_MODEL` is `gpt-4.1-mini`. When the optional storage bucket is configured, it stores JPEG food images, MongoDB saves each image's object key, and the backend issues a fresh signed URL for display.

## Web push and presenter

Generate a VAPID key pair once with `uv run python -m push`, then set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT` (a `mailto:` contact) on the Backend. `GET /push/key` returns the public key, and `POST /push/subscribe` saves the browser's subscription on the guest (`push_subscriptions` on the `guests` document, up to 10 devices). Every feed item with `notify` is pushed to that guest's devices, and devices the push service reports as gone (404 or 410) are removed. Without the keys, `/push/key` answers 503 and the app shows an in-app lock screen only.

Set `PRESENTER_KEY` on the Backend. `POST /presenter/trigger` with `X-Presenter-Key` and `{guest_name, moment | reminder}` triggers the action for every guest with that display name, ignoring case. The response reports how many guests matched and how many triggers succeeded. The presenter dashboard (`/presenter.html`) uses it from any device.

The same endpoint accepts `{guest_name, agent: "food"}` and `{guest_name, agent: "item"}`. Set the S3 variables above to the hackathon bucket containing `body_data/` and `personas/`. The food agent ranks catalog meals using available history, then looks for similar Shopee Food listings within the guest’s budget. The item agent uses recent sleep or activity to search Shopee Mall. Both post to the guest’s chat and can send a web push. With `OPENAI_API_KEY`, `RECOMMENDATION_MODEL` (default `gpt-4.1-mini`) chooses from the ranked shortlist. Local runs without a key use the first ranked choice.

Both agents use `load_recommendation_context` to read fresh MongoDB data by guest ID, merge it with local meals, and load a matching bucket persona when needed. With no health history, the food agent uses the current profile and catalog, and the item agent labels its suggestion as general. Set `RECOMMENDATION_BUCKET` instead of `S3_BUCKET` when the process should read the catalog without storing meal photos.

On Railway, the agents use the app’s private `MONGO_URL` by default. For local testing against a private Railway database, open a Railway SSH tunnel with `railway connect MongoDB --tunnel-only` and set `RECOMMENDATION_MONGO_URL` to a tunneled connection string for a MongoDB user with the `read` role. Leave `MONGO_URL` unset to keep local app writes in `DATA_DIR`. Recommendation queries match the exact guest ID across databases. Same-name local and Railway guests keep their own histories.

With imported health history, the dinner tip picks a dish the guest already eats that closes today's protein gap within the calories left, explains why and searches Shopee Food for it. Without history it falls back to the grilled chicken salad. The `weekly_recap` moment summarises the last seven logged days (calories, protein, steps, Shopee Food spend, sodium and weight), states one insight and asks what to work on. Its replies, **Plan tomorrow's meals** and **Find lighter orders**, answer from the same history without an AI key.

Calls simulate results by default. For live calls in the Ploy demo set `LIVE_CALLS=1`, the Twilio and OpenAI variables from the spec, and a comma-separated `TWILIO_VERIFIED_TEST_NUMBERS` list of team-owned numbers. The backend requires the listing number to match that list. An OpenAI key enables free-form chat through the Agents SDK.
