# Zippy

Zippy is a chat-first health assistant. Guests can ask about food and nutrition, log meals from photos, and review sleep, activity, workouts, and calories burned. The presenter can send personalized food and product suggestions or ask a guest to confirm a workout. Zippy uses a Shopee simulator for nearby food, shopping, and PIN-approved checkout.

## Run locally

1. Install Docker with Compose and obtain a MongoDB connection string for development. The backend requires MongoDB, and Compose expects a database reachable from its container. For access to the Railway database, see the [backend MongoDB setup](BE/README.md#guest-storage-on-railway).
2. Create a local `.env` in the repository root and set `MONGO_URL`. Set `MONGO_DATABASE` if your database name differs from the default `zippy`.
3. Start the frontend and backend from the repository root.

   ```sh
   docker compose up --build frontend
   ```

4. Open [Zippy](http://localhost:3000/) and create a guest session. To rehearse the scripted demo, open [Ploy's demo](http://localhost:3000/?demo=ploy).
5. Open the [presenter dashboard](http://localhost:3000/presenter.html), enter the guest's display name and the local presenter key `local-presenter`, and trigger a flow. The guest receives it in chat.

Compose uses the team's hosted Shopee simulator by default. Use a database with the `food_catalog` collection populated to try catalog lookup and food recommendations. Follow the [backend setup](BE/README.md#run-and-verify) and [environment template](BE/.env.example) to run services directly or configure OpenAI chat, voice, photo scanning, or a local simulator.

## Repository layout

| Path | What lives there |
| --- | --- |
| [FE/](FE/README.md) | Static web app, guest and presenter views, and the Caddy API proxy |
| [BE/](BE/README.md) | FastAPI, chat and voice, recommendation agents, guest storage, and integrations |
| [MCP/](MCP/README.md) | Shopee Food, Shopee Mall, and ShopeePay simulator with a Streamable HTTP MCP endpoint |
| [CRON/](CRON/README.md) | Standalone Railway cron example that logs a timestamp and exits |

See [Architecture](ARCHITECTURE.md) for the service diagram and data flows, the [API guide](FE/CHAT_API.md) for routes and event shapes, and the [demo script](ZIPPY_SPEC.md#1-the-demo) for the presentation walkthrough.

## Checks

From the repository root:

```sh
node --test FE/tests/*.cjs
docker compose config --quiet
```

Run `uv run pytest -q` from [BE/](BE/README.md#run-and-verify) and `uv run --locked pytest -q` from [MCP/](MCP/README.md#run) for their Python suites.
