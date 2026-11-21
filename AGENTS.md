# Repository guide

## Zippy

Zippy is a chat-first proactive health assistant. The demo follows Ploy from a sleep insight and a Shopee Mall purchase in the morning to a dinner suggestion, a walk and a phone reservation in the evening.

- **Demo and scope.** Read [the demo script](ZIPPY_SPEC.md#1-the-demo) before changing user-facing behavior. Use it as the acceptance test and ask before changing it. Follow [the build order](ZIPPY_SPEC.md#6-build-order).
- **Integration.** Read [the contracts](ZIPPY_SPEC.md#5-contracts) before changing routes, streams, cards, tools or prompts. Build cards from tool results. Edit agent instructions in the backend YAML and validate prompt placeholders at startup.
- **Backend configuration.** Use [BE/.env.example](BE/.env.example) for local setup and the canonical Shopee MCP endpoint. For Railway variables and optional integrations, read [the configuration section](ZIPPY_SPEC.md#9-configuration).
- **Chat frontend handoff.** Read [FE/CHAT_API.md](FE/CHAT_API.md) when wiring the chat stream, Shopee checkout, or transcription.
- **Payments and calls.** Ploy approves every payment on the simulator's ShopeePay PIN page. Zippy only requests payment. Use Shopee Food for listings and Twilio for table reservations. Use only verified team test numbers for live calls. Read [the safety rules](ZIPPY_SPEC.md#10-safety-rules) before exercising these flows.
- **Verification.** Keep external dependencies injectable and cover behavior changes with focused, offline tests. See [the test plan](ZIPPY_SPEC.md#8-testing).

## Current infrastructure

- **Hosting.** Railway runs three services: the frontend (Caddy serving `FE/` and proxying `/api/*` to the backend with the server-side `API_TOKEN`), the backend (FastAPI in `BE/`, one replica) and the Shopee simulator (`MCP/`).
- **Database.** MongoDB on the Railway private network (`MONGO_URL`, database `zippy`) stores all guest data: `guests` (profile, goals, connections and any imported health history), `wellness_days`, `meals`, `sessions`, `session_events`, `orders`, `bookings` and `reminders`. Startup creates collections and indexes. Without `MONGO_URL`, local runs fall back to JSON files under `DATA_DIR`. See [BE/README.md](BE/README.md#guest-storage-on-railway).
- **Files.** A Railway S3-compatible bucket stores meal photos. MongoDB keeps only the object key, and the backend signs URLs on read.
- **Visitors.** Each browser gets a guest cookie (`POST /visitor`). `/?demo=ploy` opens the scripted Ploy demo with its own cookie and presenter controls.
- **Health history.** A visitor can import their own history file (profile, meals, wearables, workouts, weights and body scans) with `PUT /persona`. The backend stores it on the guest, maps it into the profile goals and food log, and gives the coach a compact summary through the `get_health_history` tool. The raw log never goes to the model.
- **Frontend.** Static HTML, CSS and JavaScript with no build step. It is installable to the iOS Home Screen (`manifest.webmanifest`). `sw.js` shows web push, which still needs the backend routes described in [FE/CHAT_API.md](FE/CHAT_API.md#web-push-backend-work-needed).

## Where to work

- Frontend changes belong in `FE/`. Keep frontend setup and run commands in [FE/README.md](FE/README.md).
- Backend changes belong in `BE/`. Keep backend setup and run commands in [BE/README.md](BE/README.md).
- Model Context Protocol changes belong in `MCP/`. Keep MCP setup and run commands in [MCP/README.md](MCP/README.md).
- Reusable agent workflows live in `.agents/skills/`. Read the relevant `SKILL.md` when using a workflow.

## Verify changes

- Use the affected component's README and build configuration to find its checks. When you add a runnable component, record its setup, run, and verification commands in its README.
- When changing a shared interface, check its callers and run the relevant checks on each affected component.
- Report which checks ran and which were unavailable.
