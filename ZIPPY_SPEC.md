# Zippy build spec

Zippy is a proactive health assistant. It reads Ploy's health data, spots changes, compares products on Shopee, finds dinner, and books a table by phone. The experience centers on one chat. Ploy approves every payment with her own ShopeePay PIN.

This is the demo and implementation plan. Names are suggestions except where they form a contract with an external system or between services.

## 1. The demo

Follow Ploy through Saturday, 21 November 2026 in Bangkok. Target about 40 seconds for Scene 1 and 70 seconds for Scene 2.

- Keep the chat central and show insights, choices and actions as cards. Use the phone-sized web app's simulated lock screen for notifications.
- Show Shopee Mall and ShopeePay during shopping and Shopee Food when finding dinner. The ShopeePay PIN page belongs to the simulator and is the payment handoff.
- Dinner means walking to a restaurant and reserving a table by phone. Exclude online food ordering.
- Source products, prices, shops and phone numbers from the Shopee simulator. Use the following demo fixtures for Ploy's data.

### Ploy's demo data

| What | Value |
|---|---|
| Profile | Ploy · Silom, Bangkok · with Zippy since Nov 2026 |
| Daily goals | Sleep 7 h, deep sleep 1 h 30 min, protein 90 g, 1,900 kcal, 20 active minutes, 8,000 steps |
| Preferences | Healthy Thai, mild spice, up to 300 THB per meal. Home Sathorn Soi 8, work Silom. |
| Connected apps | Seven, including Shopee, WHOOP, Apple Health and Google Calendar. Suggestions include Boditrax, Gmail, Fitbit and Garmin. |
| Last night (WHOOP) | 00:30–05:40, 5 h 10 min. Deep 58 min (32 min short), REM 1 h, light 3 h 07 min, awake 5 min. Three hours with no deep sleep. Room brightened at 05:40. Third short night this week. |
| Recovery | 64%, “take it easy.” HRV below her usual level. Show seven days of bars. |
| Activity by 18:10 | 2,140 steps (27% of goal), 3 of 20 active minutes, 9 h sitting |
| Breakfast 07:40 | Greek yogurt, granola and banana · 420 kcal · 11 g protein · photo |
| Lunch 13:10 | Pad kra pao gai with fried egg · 690 kcal · 38 g protein · photo |
| Snack 16:00 | Fresh mango · 150 kcal · 1 g protein · chat |
| Evening totals | 1,260 / 1,900 kcal (640 left), protein 50 / 90 g, carbs 150 / 230 g, fat 45 / 63 g |

### General pages

Every page ends with an “Ask Zippy” bar.

- **Profile.** Goals, personal preferences and connections, including calendar. Shopee payments always go through Ploy's PIN.
- **Connect apps.** All, Health & wearables, and Email & calendar filter chips. Show suggestions under “For you” with Connect buttons, plus a “Connected” list with On ticks and an updated count. Shopee shops and finds food with PIN approval for payments. WHOOP reads sleep and recovery each morning. Apple Health reads steps and workouts.
- **Consent sheet.** Let Ploy choose items individually. Boditrax shares weight and body fat for the calorie goal, muscle mass for the protein goal and optional visceral fat (off by default). Use read-only access. Provide Allow and Not now, and let her turn items off or disconnect.
- **Today.** Show 64% recovery with seven-day bars. Progress rows show sleep, protein (“40 g to go · dinner idea at 18:15”), calories and active minutes (“2,140 steps · 9 h sitting”). “Zippy is on it” lists the 18:15 dinner idea and Sunday eye-mask delivery from Shopee Mall.
- **Food log.** Show a weekly date strip, macro bars, meals with photo or chat sources, and dinner “suggested by Zippy” (grilled chicken salad, about 400 kcal and +35 g protein). Use “Snap a meal or ask Zippy” with a camera button. A photo alone can log a meal.

### Scene 1 · Morning, sleep and an eye mask

1. **07:02 lock screen.** “You slept 5 h 10 m, your 3rd short night this week. Light woke you up at 5:40. Want help?” Ploy taps the unprompted notification.
2. **Sleep insight.** “Morning, Ploy. Here's last night, from the moment you fell asleep.” The WHOOP card shows deep sleep (58 min, 32 min short), a stage chart from 00:30 to 05:40, stage totals, “05:40 room got bright” and “3 h with no deep sleep.” Follow with “Light hits your room around 05:30 and keeps you out of deep sleep. An eye mask could win back 30–40 min of it.” Offer **Show me options** and **Not now**.
3. **Compare four Shopee Mall shops.** A swipeable row leads with **3D Contoured Sleep Eye Mask**, Dreamy Sleep Official, ฿199, ★4.8, “Best value for you,” “blocks 100% light, no pressure on eyes.” Then **Breathable Cotton Eye Mask**, HomeRest Store, ฿129, “soft, but light gets in…”. Show “Swipe for 2 more · ฿59 to ฿390.” Ploy taps **Buy** on the first item.
4. **Order summary.** ฿199 plus ฿30 shipping totals **฿229**. Deliver to home in Sathorn Soi 8 on Sunday, 22 November. Show **Pay with ShopeePay · 229 THB** and “You'll confirm with your ShopeePay PIN.”
5. **PIN handoff.** Open the simulator page for Dreamy Sleep Official · Shopee Mall, ฿229.00, requested by Zippy for Ploy. Ploy enters her six-digit PIN. “Zippy can find, compare and prepare. Only you can pay: every payment needs your PIN.” The presenter pauses here.
6. **Paid in chat.** “ShopeePay · approved with your PIN · 07:03.” Show **Paid ✓ Arriving tomorrow** with “Shopee Mall” and “Paid with ShopeePay” chips. Zippy says “I'll remind you to wear it at 10:30 tonight” and shows **Reminder set · 22:30**.

### Scene 2 · Evening, dinner, a walk and a booking

1. **18:15 lock screen.** A “Dinner tip” notification tells Ploy about her protein gap.
2. **Meal.** Earlier chat shows “Lunch logged from your photo: pad kra pao, 38 g protein.” Now Zippy says “You've had 50 g of your 90 g protein. This dinner closes the gap.” Show **Grilled chicken salad · +35 g protein · 400 kcal** and why it fits.
3. **Nearby places.** Three Shopee Food listings serve it. Recommend **Easy Health · 45 g protein · Caesar, sous-vide chicken · 265 THB** for the most protein.
4. **Activity and walk.** Show **2,140 steps today · 27% of goal** and suggest a walk to dinner. Ploy agrees.
5. **Booking consent.** Easy Health takes no online bookings. Ask to call for a table for one at 19:00. Ploy agrees.
6. **Call Easy Health.** The chat header shows **Calling…**.
7. **No answer.** Show “Called Easy Health · no answer after 40 s.” Salad Factory is five minutes closer and has a similar menu. Offer **Call Salad Factory**.
8. **Call Salad Factory.** The restaurant picks up and the header shows **On a call**.
9. **Booked.** Show “Salad Factory · call ended · 00:34 · ‘Yes, 7pm for one.’” Confirm the table under Ploy, show a 10-minute walking route and set a leave-by reminder for 18:48. When it fires, show “Time to go. 10 min walk, route is on your lock screen.”
10. **19:40 final shot.** Show a daily summary card with every goal green.

### Scope

Use simulated payments, demo health data, a phone-sized web app and test booking calls. Exclude real payments, online food ordering, restaurant callbacks, calls to Ploy and a native app. Defer production authentication, secrets management, durable or managed storage and production scheduling. Keep storage, health data and auth behind small interfaces. Real WHOOP data and a voice coach are stretch goals.

## 2. Stack

| Piece | Choice |
|---|---|
| Hosting | Railway services for frontend, backend, cron and Shopee MCP |
| CI/CD | GitHub Actions runs tests, then deploys to Railway |
| Frontend | Node.js phone-sized web app |
| Backend | Python 3.13, uv, FastAPI and uvicorn with websockets |
| Agents | OpenAI Agents SDK (`openai-agents` ≥ 0.24), `Agent` for chat and proactive messages, `RealtimeAgent` for calls, built-in MCP client |
| Chat | SDK default `gpt-5.6-luna` with reasoning `none`, also used for meal photos |
| Calls | `gpt-realtime-2.1`, transcription `gpt-live-transcribe` with `languages: ["en", "th"]`, Twilio 9.x REST and Media Streams |
| Shopee | Simulator at `https://shopee-sim-production.up.railway.app/mcp` |
| Data | MongoDB on Railway for guest data (JSON files under `DATA_DIR` locally), an injectable demo health provider, and optional imported health history per guest. WHOOP is a stretch goal. |
| Images | Railway S3-compatible bucket for meal photos. MongoDB stores object keys and the backend signs URLs. |
| Scheduling | Railway cron and a manual demo trigger |
| Other Python libraries | `python-dotenv`, `pyyaml`, `python-multipart`, `boto3`, `httpx` |

## 3. Architecture

- **Frontend (`FE/`).** Renders streamed chat, cards, quick replies, header status, the simulated lock screen, general pages and order summary. Polls the feed and opens the PIN page.
- **Backend (`BE/`).** Hosts REST, NDJSON, Twilio callbacks and the media WebSocket. Owns settings, the MongoDB store (JSON fallback locally), demo data and clock, prompts, the coach, MCP client, photos and S3 URLs, call agent and bridge, and reminders.
- **Cron.** Calls `POST /proactive` and exits. The demo trigger can invoke the same moments.
- **Shopee MCP (`MCP/`).** Separate simulator service with demo products and restaurants, plus team-owned test numbers. It supplies Mall, Food listings and the ShopeePay handoff.
- **Deployment.** GitHub Actions deploys tested services to Railway.

```text
Frontend ── REST, chat stream, feed ──► FastAPI ◄── proactive POST ── Cron
FastAPI ──► Agents SDK ──► OpenAI chat / Shopee MCP
FastAPI ──► MongoDB (JSON locally) / S3 bucket / health provider
FastAPI ── Twilio REST calls.create ──► Twilio
Twilio ── Media Stream /media-stream ──► FastAPI bridge ⇄ OpenAI Realtime
Twilio ── POST /call-status ──► FastAPI ──► booking, feed and coach follow-up
Frontend ── approve_url ──► ShopeePay simulator PIN page
```

## 4. How the flows work

### Proactive moments and chat

- At 07:02, 18:15 and 19:40, call `POST /proactive {moment}` for sleep, dinner and summary. Generate the message and cards before publishing the notification. Save them to the feed and mark the first item as a notification. Tapping the notification opens the chat at that item.
- Typing or tapping a quick reply calls `POST /chat {message, session_id}`. Show a varying waiting line such as “One moment…” and stream text, tool status, cards and quick replies.
- The coach picks options using IDs from tool results. The backend renders facts in cards. Data tools emit sleep, activity, booking, walk and reminder cards. For choices, the coach uses the `show_*` tools.

### Shopping and payment

1. Search Shopee Mall with `search_products`. Compare up to four shops by light blocking, comfort, price and rating. Call `show_products(item_ids, best_item_id, reason)` and offer quick replies.
2. **Buy** calls `POST /actions/buy {item_id}` directly. `place_mall_order` returns the facts for the order summary.
3. **Pay** calls `POST /actions/pay {order_id}` directly. `request_payment` returns an `approve_url`. Open it for Ploy's PIN entry.
4. Poll `GET /shopee-orders/{id}`, backed by `get_order_status`. On approval, add the paid card to the feed and send the coach a payment update. The coach calls `set_reminder("22:30", "Wear your eye mask")`.
5. Cancel the unpaid Shopee order if Ploy abandons the sheet.

### Dinner and booking

1. At 18:15, use Ploy's protein gap, tastes and budget to show one meal and a short reason via `show_meal`. Call `find_similar_dishes` with the dish, calories and protein. Rank by protein, then distance, then price, and call `show_places`. Call `get_activity_today` and suggest walking when activity is low.
2. After Ploy agrees, `book_table_by_phone(restaurant_id, party_size, time)` uses `get_menu` for the name, phone and location. Create a `calling` booking, dial and return immediately. The header shows **Calling…**, then **On a call** when the media stream starts and the booking becomes `in_call`.
3. Dial with Twilio `calls.create` using `<Connect><Stream>`, `<Parameter>` values for purpose and booking ID, a 40-second ring timeout and answering-machine detection. The call agent speaks first, asks for one at 19:00 under Ploy and uses `report_booking_result(outcome, confirmed_time, quote, notes)` once. The outcomes are `booked`, `full` and `other`. Capture the callee's words, say goodbye and request `end_call`.
4. Treat Twilio's `no-answer`, `busy`, `failed` or a detected machine as `no_answer`. Every completed outcome adds a feed card with the restaurant, result, available `CallDuration` and quote, and sends an update to the coach.
5. After no answer, the coach offers the next closest similar place from the earlier listings. After booking, confirm the reservation and show the walk route and leave-by reminder.
6. `plan_walk(restaurant_id, arrive_by)` returns walking minutes based on shop distance at about 5 km/h or a maps API, a leave-by time and a Google Maps walking link. `set_reminder(at, message)` persists the reminder. A one-replica scheduler reloads pending reminders on startup and turns due reminders into feed notifications. Trigger them manually during the demo.

### Meal photos and voice

- `POST /food-log/photo` accepts a multipart photo, stores it in S3 and asks the chat model for structured `{dish, kcal, protein_g, carbs_g, fat_g}`. Save the entry with its photo URL and post the nutrition summary in chat.
- After both scenes work, the stretch voice coach can reuse chat tools through a browser WebSocket, a `RealtimeAgent` and 24 kHz PCM16 audio.

## 5. Contracts

### Backend routes

| Route | Caller and behavior |
|---|---|
| `GET /health` | Railway health check, returns `{"status":"ok"}` |
| `GET /visitor`, `POST /visitor` | Check for a guest cookie or create a guest profile from a display name and optional food preferences and budget |
| `DELETE /visitor` | Clear the active visitor cookie and return to guest setup. Stored records are retained. |
| `GET /profile`, `PUT /profile` | Frontend reads or updates goals, preferences and connections |
| `GET /persona`, `PUT /persona` | Frontend imports or reads the visitor's own health history. Import updates profile targets and the food log and feeds the coach's summary tool. |
| `GET /today` | Frontend reads recovery, sleep, nutrition, activity and upcoming actions |
| `GET /food-log?date=` | Frontend reads meals and totals |
| `POST /food-log/photo` | Frontend uploads a meal photo |
| `POST /chat` | Frontend receives streamed NDJSON |
| `GET /sessions`, `GET /sessions/{id}` | List and restore the visitor's chats, with their cards and feed cursor |
| `GET /feed?session_id=&after=` | Frontend polls every 1–2 seconds for proactive and asynchronous items |
| `POST /actions/buy`, `POST /actions/pay` | Frontend places a Mall order and requests payment |
| `GET /shopee-orders/{id}` | Frontend polls order status while the PIN page is open |
| `GET /bookings/{id}` | Frontend checks booking status |
| `POST /proactive {moment}` | Cron or demo triggers `morning_sleep`, `dinner_tip`, `daily_summary` or `weekly_recap` |
| `POST /demo/reset`, `POST /demo/trigger` | Presenter resets or triggers a moment or reminder |
| `POST /presenter/trigger` | Presenter dashboard fires a moment for a guest by display name, authorized by `X-Presenter-Key` |
| `GET /push/key`, `POST /push/subscribe` | Frontend reads the VAPID public key and saves the browser's push subscription. Notifications are pushed to saved devices. |
| `POST /call-status` | Twilio callback with `CallStatus`, `CallDuration` and `AnsweredBy` |
| `WS /media-stream` | Twilio streams call audio |
| `WS /voice` | Browser voice coach (stretch) |

Frontend, cron and demo routes use shared `API_TOKEN` through an Authorization Bearer header or a `token` WebSocket query parameter. Browser data routes also require the guest cookie. The Ploy walkthrough uses a separate demo cookie selected by the `X-Zippy-Demo: 1` header. Validate `X-Twilio-Signature` on Twilio routes. Set CORS to `FRONTEND_ORIGIN`.

### Chat stream and feed

The chat stream uses `application/x-ndjson` with one object per line.

```jsonl
{"type":"delta","text":"One fragment"}
{"type":"tool","name":"get_sleep_last_night"}
{"type":"card","card":{"kind":"sleep_insight"}}
{"type":"quick_replies","options":["Show me options","Not now"]}
{"type":"done"}
{"type":"error","message":"Request failed"}
```

End with either `done` or `error`. Treat text before and after tool calls as separate messages with a blank line between them. Cancel the run on browser disconnect. Keep one chat turn in flight and buffer partial NDJSON lines.

Feed items have `{id, at, role, text?, card?, quick_replies?, notify?, header_status?}`. Roles are `assistant` and `system`. Notifications have `{title, body}`. Header statuses are `online`, `calling` and `in_call`. Deduplicate by ID. Send replies to Ploy's own messages through the chat stream.

### Cards

| `card.kind` | Data |
|---|---|
| `sleep_insight` | Deep minutes, goal, shortfall, stage timeline and totals, events, source |
| `product_compare` | Up to four products with `item_id, name, shop, price_thb, rating, image_url, note`, plus `best_item_id` and `more: {count, price_range}` |
| `order_summary` | Item, shipping, total, arrival date, address, `order_id` |
| `payment_status` | Paid, item, total, arrival, chips |
| `reminder` | `at, message` |
| `meal` | `dish, kcal, protein_g, why` |
| `places` | Entries with `shop_id, name, dish, protein_g, price_thb, distance_km` |
| `activity` | `steps, steps_goal_pct, active_minutes` |
| `call` | `restaurant, status, duration_s, quote`. Status is `calling`, `no_answer` or `ended`. |
| `walk_route` | `minutes, leave_by, maps_url` |
| `daily_summary` | Each goal with its value and whether it was met |

### Data and tools

- **Profile.** Name, location, member since, goals, food preferences, home, work, budget and connections `[{app, connected, shares[]}]`.
- **Day data.** One per date with sleep times, stages, events and short nights this week, recovery percentage, HRV note and seven-day bars, plus steps, active minutes and sitting hours.
- **Food entry.** `id, date, time, meal, dish, kcal, protein_g, carbs_g, fat_g, source, photo_url?`. Sources are `photo`, `chat` and `suggested`.
- **Booking.** `id, shop_id, restaurant_name, phone, party_size, time, name, status, call_sid, duration_s, quote, created_at`. Statuses are `calling`, `in_call`, `booked`, `no_answer`, `full` and `failed`.
- **Reminder.** `id, at, message, status`. Statuses are `scheduled` and `sent`.
- **Feed and chat history.** Store ordered turns and feed events per guest conversation. MongoDB stores these records, guest profiles, mock wellness dates, meal metadata and workflow state. Local development can fall back to JSON under `DATA_DIR`. The bucket stores food images.

| Tool owner | Tools |
|---|---|
| Coach data | `get_profile`, `get_sleep_last_night`, `get_today`, `get_activity_today`, `get_food_log`, `log_meal` |
| Coach choices | `show_products`, `show_meal`, `show_places` |
| Coach actions | `book_table_by_phone`, `get_booking`, `plan_walk`, `set_reminder`, `suggest_replies` |
| Shopee shopping | `search_products`, `place_mall_order`, `request_payment`, `get_order_status`, `cancel_order` |
| Shopee listings | `find_similar_dishes`, `get_menu`, `search_restaurants` |
| Call agent | `report_booking_result`, `end_call`, both bound to the specific booking |

### Prompts

Keep prompts in one backend YAML file and restart after edits. Validate required keys and supported placeholders at startup.

- **`coach.shared`**. Be brief and warm. Use one chart, one reason and one fix. Get numbers from tools and use `show_*` for choices. Respect Ploy's goals, tastes and budget. Explain that Ploy approves payment. Use Food listings to suggest places, offer a walk when Ploy is inactive, and book by phone with permission. After a failed call, suggest the next closest similar place. Reply in the language of her latest message.
- **`coach.chat_style`**. Plain text in one or two short paragraphs.
- **`proactive.morning_sleep`, `proactive.dinner_tip`, `proactive.daily_summary`**. Define data to inspect, cards, a one-line notification and the first chat message.
- **`phone.rules`**. Speak first in `{language}` and switch if requested. Keep turns short and read the time and party size back. Use confirmed details, keep the call focused on the reservation, say goodbye and call `end_call`.
- **`phone.book_table`**. Use `{restaurant_name}`, `{party_size}`, `{time}` and `{name}`. Confirm the time, capture the exact words and report the outcome once.

## 6. Build order

1. **Skeleton and deployment.** Add backend settings, `/health`, JSON store, demo seed, `DEMO_NOW`, reset, token and CORS. Connect the phone-sized frontend shell and deploy from GitHub Actions. Done when a push updates the demo URL and Today shows Ploy's numbers.
2. **Chat.** Build the stream, waiting line, cards, replies, feed polling and coach data tools. Done when “How did I sleep?” shows the sleep card.
3. **General pages.** Build Profile, Connect apps and consent, Today and Food log from demo data.
4. **Scene 1.** Build the prefilled morning notification, MCP search and comparison, direct Buy and Pay actions, PIN handoff, status polling, paid card and reminder. Rehearse end to end in about 40 seconds and cancel your test orders.
5. **Scene 2 before the calls.** Build the dinner notification, meal and listings cards, activity and walk suggestion.
6. **Scene 2 calls.** Build the call agent, media bridge and callback, no-answer handling, status and cards, coach follow-ups, route, reminder and daily summary. Rehearse end to end in about 70 seconds with the first call unanswered and the second booked.
7. **Meal photos.** Upload to S3, read the photo and log the entry.
8. **Scheduling.** Add the Railway cron job and in-process reminder runner.
9. **Stretch.** Add real WHOOP data and the voice coach after both scenes work.
10. **Deployed rehearsal.** Reset, time both scenes and fix anything slower than the script. Keep a recorded rehearsal as a backup.

Write focused tests alongside each step.

## 7. Pitfalls

### Demo reliability and Agents SDK

- Pin `DEMO_NOW`, restore the seed with `POST /demo/reset` and fire moments and reminders with `POST /demo/trigger`.
- Budget about 2.5–3 seconds per model call and 0.3 seconds per tool call, with occasional model stalls of up to 30 seconds. Precompute proactive replies. Use direct Buy and Pay actions and go straight to `find_similar_dishes` for dinner.
- Seed the simulator with masks spanning ฿59–390, Easy Health, Salad Factory, dishes and team-owned phone numbers before rehearsal.
- Write SDK tools as `async def` so they share the backend event loop. Strict tool schemas use required parameters with nullable or empty values where appropriate.
- Check for duplicate tool names across local and MCP tools at startup. Check installed SDK source under `.venv/lib/python3.*/site-packages/agents/` when implementing against its APIs.

### Shopee MCP

- Open the shared connection in the FastAPI lifespan once. Open and close it in the same task. Use `cache_tools_list=True`, `timeout=20`, `client_session_timeout_seconds=30` and `max_retry_attempts=1`.
- The MCP v2 client uses `is_error`, `input_schema` and `structured_content`. Parse one JSON object per result text block. Search defaults to Silom, Bangkok.
- Check whether the returned `approve_url` can be embedded. If embedding fails, open a new tab and poll order status.

### Twilio and Realtime

- Use an upgraded Twilio account with Thailand Voice Geographic Permissions. Trial accounts play a message, require a callee keypress and can only call verified numbers.
- Set `timeout=40` and `machine_detection="Enable"` for unanswered-call handling. Easy Health's team number should ring unanswered. Salad Factory's team number should reach a teammate who confirms the booking.
- Stream URLs cannot carry query strings. Use bidirectional `<Connect><Stream>` and pass `purpose` and `booking_id` as `<Parameter>` values. Read the Twilio `start` event before opening the Realtime session. Send raw `{"type":"response.create"}` after opening so the agent speaks first.
- Use G.711 μ-law at 8 kHz in both directions. Batch 20 ms frames into roughly 50 ms (400-byte) chunks with a flush loop. Use `semantic_vad` with `interrupt_response` and `create_response`. Give transcription the English and Thai language list.
- For barge-in, send a `mark` after outbound audio chunks, report confirmed bytes to `RealtimePlaybackTracker` and send `clear` on `audio_interrupted`.
- `end_call` requests a hang-up. Wait for about 1.5 seconds of quiet and confirmed playback marks, bounded by 15 seconds, then call Twilio REST `calls(sid).update(status="completed")`.
- Validate signatures against the configured public URL built from `TWILIO_PUBLIC_BASE_URL` and the path. For the WebSocket handshake, use the public `wss://…/media-stream` URL and accept the trailing-slash variant.
- Run synchronous Twilio calls with `asyncio.to_thread`, retain background tasks in a set, and set uvicorn's `ws_max_size` to 64 KB.

### Data, images and deployment

- Run one backend replica for JSON storage, reminders and call bridges. Write each JSON file to a temporary sibling, then rename atomically. Railway deploys replace container disk. Mount a volume at `DATA_DIR` if persistence is needed.
- Load packaged prompts with `importlib.resources`. Keep Apple Health steps in the demo fixture. For the WHOOP stretch goal, authorize the demo account with OAuth 2.0 beforehand and convert kJ to kcal by dividing by 4.184.
- Resize meal photos before upload. Provide presigned GET URLs lasting at least an hour and use the same URL for model image input. Store dish images by item ID.
- Set CORS and the frontend backend URL for the separate services. Rebuild the frontend after changing any environment variable baked in at build time. Treat Web Push as optional. iPhone Web Push needs a home-screen installation.
- Railway cron uses UTC (07:00 Bangkok is `0 0 * * *`), has a five-minute minimum interval and expects the job to exit. Set each service's root or Dockerfile path, honor Railway's `PORT`, run containers as non-root and omit BuildKit cache mounts.
- Run tests before GitHub Actions deploys each service with the Railway CLI and `RAILWAY_TOKEN`. If TLS inspection blocks `uv`, `--offline` can use dependencies already in its cache.

## 8. Testing

Inject telephony, the Realtime session factory, MCP server, health provider, S3, clock and store through the backend app factory. Tests run offline. Use a fake MCP server with the simulator's tool names and realistic product, dish, menu, payment and order-status results.

Cover streamed events and tool-backed cards, feed deduplication, Buy → summary → Pay → paid, booking the correct number and rejecting unknown shops, no answer and machine handling, a confirmed booking with duration and quote, reminders, photo logging, reset, signature and token rejection, and startup failure for invalid prompts.

Starlette `TestClient.websocket_connect` uses host `testserver`. End the stream and wait for the fake session to close before exiting its context to avoid `CancelledError`.

## 9. Configuration

### Backend

For local development, copy [`BE/.env.example`](BE/.env.example) to `BE/.env`. The example targets the Shopee simulator at `https://shopee-sim-production.up.railway.app/mcp`. Use the same endpoint for `SHOPEE_MCP_URL` in Railway unless deliberately testing a different simulator. Set the shared production token in Railway Backend → Variables. Keep local listen settings in the local environment and use Railway's injected port.

| Variable | Requirement or default |
|---|---|
| `OPENAI_API_KEY` | Enables free-form chat and is required for live calls and meal photo analysis |
| `API_TOKEN` | Shared secret for frontend, cron and demo routes. Required on Railway. Local example uses `local-zippy`. |
| `FRONTEND_ORIGIN` | Allowed CORS origin. Defaults to `http://localhost:3000` for local development. |
| `SHOPEE_MCP_URL` | Simulator endpoint. Use the URL in `BE/.env.example`. |
| `LIVE_CALLS` | Defaults to `0` for simulated calls. Set to `1` to enable Twilio. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Required for live calls on an upgraded account |
| `TWILIO_PHONE_NUMBER` | Outbound caller ID for live calls |
| `TWILIO_PUBLIC_BASE_URL` | Public HTTPS origin for Twilio callbacks, with no path |
| `TWILIO_VERIFIED_TEST_NUMBERS` | Comma-separated team-owned E.164 numbers. The simulator listing must match. |
| `RING_TIMEOUT_SECONDS` | Optional, default 40 |
| `CALL_LANGUAGE` | Optional starting language, e.g. English or Thai |
| `TRANSCRIPTION_LANGUAGES` | Optional, default `en,th` |
| `REALTIME_MODEL`, `REALTIME_VOICE` | Optional, default `gpt-realtime-2.1` and the model's voice |
| `MAX_CALL_SECONDS` | Optional, default 300 |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET` | For images. Use `AWS_SESSION_TOKEN` with temporary credentials. |
| `HEALTH_PROVIDER` | Optional, `demo` by default or `whoop` |
| `WHOOP_*` | OAuth client ID, secret and refresh token for the stretch integration |
| `DATA_DIR` | Optional, defaults to `./data` |
| `DEMO_NOW` | Optional pinned clock, e.g. `2026-11-21T07:02:00+07:00` |
| `HOST`, `PORT` | Local example listens on `127.0.0.1:8080`. Railway's backend image binds to `0.0.0.0` by default and reads Railway's `PORT`. |

Frontend and cron use `BACKEND_URL` and `API_TOKEN`. GitHub Actions uses the `RAILWAY_TOKEN` secret. Restaurant phone numbers come from the simulator.

## 10. Safety rules

- Ploy enters her PIN only on the ShopeePay simulator page. Zippy can prepare orders and request approval. It must never ask for, enter or store the PIN, or invoke a tool that executes payment.
- Calls ring real phones. Verify that simulator phone numbers belong to the team before any live call. Dial only those test numbers.
- Keep the public demo URL private. The demo has no login and its shared browser-visible token only limits casual access. Production needs real authentication.
- On the shared simulator, change or cancel only orders you created. Clean up your own test orders.
- Keep personal health responses, photo URLs and tokens out of logs. Keep secrets in Railway variables or GitHub secrets and exclude `.env` from Docker images with `.dockerignore`.
- Use a different local test port if a teammate is using 8000. Stop only your server by PID.

## 11. Working rules

- Treat Section 1 as the acceptance test and ask before changing the demo script.
- Edit agent instructions in YAML. Register each new placeholder and supply it at every applicable render site.
- Build cards from tool results, including prices, other numbers and phone numbers.
- Update the API contracts alongside frontend and backend changes. Keep external dependencies injectable and cover behavior changes with focused tests.
- Backend commands from its service root include `uv sync`, `uv run pytest -q`, `uv run python -m <package>.main`, `ngrok http 8000` for local Twilio tests and `docker build -t <name> .`.

## Demo details to confirm

- The 00:30–05:40 sleep window includes five minutes marked awake. Confirm which duration the notification and Today card should call time asleep.
- The eye mask arrives Sunday, while the wear reminder is set for Saturday at 22:30.
- The suggested salad adds 35 g against a 40 g protein gap. The Easy Health listing has 45 g. The final shot also needs goal values for 19:40.
- The scripted 40-second ring and 34-second answered call total 74 seconds before the other beats in the roughly 70-second scene.
