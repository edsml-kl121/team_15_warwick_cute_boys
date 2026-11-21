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

The clock uses the real time in Bangkok. Set `DEMO_NOW`, for example to `2026-11-21T07:02:00+07:00`, to pin it for a rehearsal. The demo reset only cancels unpaid orders created in that run.

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

Startup creates the collections and indexes idempotently. To run the initializer separately from a machine with private database access, run `uv run python -m storage` from `BE/` with `MONGO_URL` configured.

| Collection | Contents |
| --- | --- |
| `guests` | Cookie-token hash, profile, preferences, goals, sharing choices and imported `persona` health history |
| `wellness_days` | Legacy shared sample dataset. Excluded from guest reads. |
| `food_catalog` | Food catalog under `_id: "food_db"`, with a `foods` array and private image object URLs |
| `guest_health_imports` | Explicitly staged sample imports keyed by case-insensitive display name, applied on guest creation |
| `meals` | Guest-owned meal entries and optional food image keys |
| `sessions`, `session_events` | Guest-owned conversations, workflow state, completed turns, cards and feed events |
| `orders`, `bookings`, `reminders` | Guest-owned actions and their statuses |

Keep one Backend replica. For local development against Railway MongoDB, start a private tunnel with `railway connect MongoDB --tunnel-only` and set `MONGO_URL` to its loopback connection string before running the backend. For Compose, supply a `MONGO_URL` reachable from the backend container. The backend requires MongoDB and scopes guest data to the guest cookie. The same display name can represent different guests.

`PUT /persona` imports a visitor's own health history as one JSON document (`profile`, `food_history_log`, `wearable_daily`, `workouts`, `weights`, `body_composition_scans`). The backend validates it, stores it on the guest, applies the calorie and macro targets, name, area, tastes and connected sources to the profile, and merges that day's meals into `GET /food-log`. The coach's `get_health_history` tool returns a compact summary of it, never the raw log. `GET /persona` returns the stored document.

Set `OPENAI_API_KEY` to enable meal scanning. Each scan sends a resized JPG to one vision model using the Responses API and saves the estimated foods, portions and totals. The default `FOOD_SCAN_MODEL` is `gpt-4.1-mini`. When the optional storage bucket is configured, it stores JPEG food images, MongoDB saves each image's object key, and the backend issues a fresh signed URL for display.

Menu and restaurant pictures for recommendation cards also come from the bucket. Upload them as `dishes/<dish-slug>.jpg` and `restaurants/<shop_id>.jpg` (`.webp` and `.png` also work). The slug is the dish name in lowercase with runs of other characters replaced by `-`, for example `dishes/spaghetti-bolognese.jpg` or `restaurants/s_easy_health.jpg`. The backend signs a URL when the file exists, even without `OPENAI_API_KEY`. Otherwise the app falls back to its bundled demo photos, then to the simulator's cuisine photo.

## Web push and presenter

Generate a VAPID key pair once with `uv run python -m push`, then set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT` (a `mailto:` contact) on the Backend. `GET /push/key` returns the public key, and `POST /push/subscribe` saves the browser's subscription on the guest (`push_subscriptions` on the `guests` document, up to 10 devices). Every feed item with `notify` is pushed to that guest's devices, and devices the push service reports as gone (404 or 410) are removed. Without the keys, `/push/key` answers 503 and the app shows an in-app lock screen only.

Set `PRESENTER_KEY` on the Backend. `POST /presenter/trigger` with `X-Presenter-Key` and `{guest_name, moment | reminder}` triggers the action for every guest with that display name, ignoring case. The response reports how many guests matched and how many triggers succeeded. The presenter dashboard (`/presenter.html`) uses it from any device.

The same endpoint accepts `{guest_name, agent: "food"}` and `{guest_name, agent: "item"}`. The food agent sends a catalog meal based on the guest’s history. When the guest replies **Recommend places nearby**, the chat searches Shopee Food near their selected location. The item agent uses recent sleep or activity to search Shopee Mall. Both agents post to the guest’s chat and can send a web push. With `OPENAI_API_KEY`, `RECOMMENDATION_MODEL` (default `gpt-4.1-mini`) chooses from the ranked shortlist. Local runs without a key use the first ranked choice.

Both agents read the authenticated guest’s MongoDB profile, wearable history and meals. The food agent also reads the catalog from MongoDB. The bucket supplies images. Explicitly imported sample readings and meals are labeled and used when the corresponding personal history is empty. The item agent reports when no qualifying sleep or activity reading exists.

Other app clients can use `POST /recommendations/food`, `POST /recommendations/food/places`, and `GET /recommendations/health-history` with the guest cookie and backend API token. Request and response shapes are documented in [the frontend API guide](../FE/CHAT_API.md).

The `weekly_recap` moment summarises the last seven logged days (calories, protein, steps, Shopee Food spend, sodium and weight), states one insight and asks what to work on. Its replies, **Plan tomorrow's meals** and **Find lighter orders**, answer from the same history without an AI key.

Calls simulate results by default. For live calls in the Ploy demo set `LIVE_CALLS=1`, the Twilio and OpenAI variables from the spec, and a comma-separated `TWILIO_VERIFIED_TEST_NUMBERS` list of team-owned numbers. The backend requires the listing number to match that list. An OpenAI key enables free-form chat through the Agents SDK. Chat uses `gpt-6.1-sol` on the ultrafast service tier with reasoning `low` by default. Override it with `CHAT_MODEL`, `CHAT_SERVICE_TIER` and `CHAT_REASONING_EFFORT`; `CHAT_SERVICE_TIER=default` uses the standard tier. Ultrafast costs more than the standard tier and has its own rate limits.
