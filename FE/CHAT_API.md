# Zippy chat API handoff

Use the [Zippy API contracts](../ZIPPY_SPEC.md#5-contracts) for route and card definitions. The backend owns account data, chat history, the Shopee MCP connection, orders, and any S3 access. The frontend displays the response and sends explicit user actions.

## Connect

The chat client defaults to `./api/`. Caddy strips the `/api` prefix before forwarding to `BACKEND_URL` and adds the server-side `API_TOKEN`. Set matching tokens on both deployed servers. If hosting the frontend on S3 later, set the `zippy-api` meta tag to the HTTPS prefix of an authenticated API gateway or frontend proxy. Keep API tokens and AWS credentials out of static files.

First arrival calls `GET /visitor` and shows guest setup if `ready` is false. Submit `POST /visitor` with a display `name`, optional `food` and optional `budget_thb`. The backend sets a same-origin HTTP-only cookie. Open `/?demo=ploy` for the Ploy scenario. The frontend sets the `X-Zippy-Demo: 1` header and the backend issues a separate demo cookie.

## Chat and shopping

1. Accept `POST /chat` with `{session_id, message}`. The browser generates a conversation ID and the guest cookie scopes it to its owner. Return `application/x-ndjson` and finish with a `done` or `error` event. On return, `GET /sessions` lists conversations and `GET /sessions/{id}` returns ordered chat turns, cards and feed events with `last_feed_id` for polling.
2. Send `delta` events for text, `card` events for results, and `quick_replies` events for tap-to-send suggestions. Use tool data from the current session. For empty searches, send a factual text response and omit the card.
3. Accept `POST /actions/buy` with `{session_id, item_id}` after the user chooses a product. Return the `order_summary`, including `order_id`, `item` (`name`, `shop`, `price_thb`), `shipping_thb`, `total_thb`, and optional `arrival_date` and `address`. Accept `POST /actions/cancel` with `{session_id, order_id}` when the user leaves the review without opening checkout.
4. Accept `POST /actions/pay` with `{session_id, order_id}` after explicit approval to continue. Return `approve_url` for the hosted ShopeePay page. The browser opens that page and polls `GET /shopee-orders/{order_id}?session_id=…`. Report payment only after provider verification. Publish the receipt and any reminder to `GET /feed?session_id=…&after=…` with increasing IDs so they appear once.

## Reference fixtures

Use these sample values for offline tests and visual review. Runtime responses come from the backend. In particular, use the actual MCP product ID, current price, shop and URL for each search result.

```jsonl
{"type":"delta","text":"Here’s a contoured eye mask I found on Shopee Mall."}
{"type":"card","card":{"kind":"product_compare","best_item_id":"p_eyemask","products":[{"item_id":"p_eyemask","name":"3D Contoured Sleep Eye Mask","shop":"Dreamy Sleep Official","price_thb":199,"rating":4.8,"note":"Blocks light without pressing on your eyes"}]}}
{"type":"quick_replies","options":["Show me more options","Not now"]}
{"type":"done"}
```

The reference order is 199 THB plus 30 THB shipping, totaling 229 THB. An example `order_summary` response follows.

```json
{
  "kind": "order_summary",
  "order_id": "example-order",
  "item": {
    "item_id": "p_eyemask",
    "name": "3D Contoured Sleep Eye Mask",
    "shop": "Dreamy Sleep Official",
    "price_thb": 199
  },
  "shipping_thb": 30,
  "total_thb": 229,
  "arrival_date": "2026-11-22",
  "address": "Sathorn Soi 8"
}
```

| Kind | Example field values |
| --- | --- |
| `sleep_insight` | `deep_minutes: 58`, `minutes: 310`, `goal_minutes: 90`, `shortfall_minutes: 32` |
| `meal` | `dish: "Grilled chicken salad"`, `protein_g: 35`, `kcal: 400` |
| `places` | `places: [{ "name": "Salad Factory · Silom", "dish": "Grilled chicken Caesar", "price_thb": 220, "protein_g": 35 }]` |
| `activity` | `steps: 2140`, `steps_goal_pct: 27`, `active_minutes: 3` |
| `daily_summary` | `goals: [{ "key": "protein_g", "value": 92, "goal": 90, "met": true }]` |

## Transcription and meal photos

Browser speech recognition supplies interim words where supported. Optionally set the `zippy-transcribe` meta tag to a separate transcription endpoint. Accept multipart `audio` and return `{"text":"…"}`. This fallback transcribes after capture ends. The current FastAPI backend has the meal photo route, but no browser transcription route.

The camera uses `POST /food-log/photo?session_id=…&stream=true` with multipart `file`. The response streams NDJSON events with `type: "progress"` and `stage: "analyzing"` or `"saving"`. A terminal `done` event carries the saved `meal`, including per-food `items` and an `uncertainty` note. A terminal `error` event carries a user-facing `message`. Clients that omit `stream` receive the saved meal as regular JSON. The backend adds the summary to the session feed when it logs the meal.

MongoDB holds the meal and its image key when an image is stored. The Food Log response includes a freshly signed `photo_url` when an image is available.

## Integration acceptance

- Submit a question and confirm that streamed text, product cards, and quick replies appear from the API. An empty search must leave the conversation without a product card. An error must offer Retry.
- Review a sandbox product and confirm that the quote uses backend prices. Complete payment only through the hosted provider. Confirm that the receipt appears once, after backend verification.
- Review the selected backend’s source configuration before connecting personal data. Keep account storage and authentication on the server.

## Dashboard pages

The Today, Food log, Profile and Connect apps pages read `GET /today`, `GET /food-log?date=YYYY-MM-DD` and `GET /profile`. Connect apps writes the whole profile back with `PUT /profile`, adding or updating one `{app, connected, shares}` entry. The app catalog (descriptions, logos and what each app can share) lives in `pages.js`. Connection state comes only from the backend.

Feed items may carry `notify: {title, body}`, which shows the simulated lock screen, and `header_status` (`online`, `calling`, `in_call`), which updates the chat header.

## Health history import

Profile › Health data reads `GET /persona` (404 until imported) and imports a JSON file with `PUT /persona`. The file follows the persona shape: `profile` (requires `persona_id` and `display_name`), `food_history_log`, `wearable_daily`, `workouts`, `weights` and `body_composition_scans`. The frontend rejects files over 5 MB before upload. Imported meals appear in the Food log for their dates, and Shopee Food orders show their restaurant.

## Presenter dashboard

`presenter.html?session=<session_id>` lists every trigger flow: morning sleep, eye mask reminder (22:30), dinner tip, time to walk to dinner (leave-by time) and daily summary, plus reset. It calls the existing `POST /demo/trigger` with `{session_id, moment}` or `{session_id, reminder: "HH:MM"}` and `POST /demo/reset`. Open it from the app menu under Presenter so the session ID is filled in. **Preview here** shows sample copy as a local notification without the backend.

The Caddy proxy adds the server token to demo routes. Anyone who can reach the frontend can trigger or reset the demo. Restrict the frontend URL or remove the demo routes from the Caddy matcher outside rehearsals.

## Web push (backend work needed)

The frontend is ready: the app installs to the iOS Home Screen with `manifest.webmanifest`, `sw.js` shows pushes, and the menu's **Turn on notifications** subscribes. iPhone push needs iOS 16.4 or later, HTTPS, and Zippy opened from the Home Screen. The backend needs:

1. **VAPID keys.** Generate a key pair once and keep the private key in an environment variable, such as `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` and `VAPID_SUBJECT=mailto:team@example.com`.
2. **`GET /push/key`** returns `{"public_key": "<base64url VAPID public key>"}`.
3. **`POST /push/subscribe`** accepts `{session_id, subscription: {endpoint, expirationTime, keys: {p256dh, auth}}}`. Store subscriptions per session and deduplicate by `endpoint`. The browser posts again whenever a chat first connects, so one device can belong to several sessions.
4. **Send.** Whenever a feed item with `notify` is emitted, send a push to that session's subscriptions, for example with `pywebpush`. Use this payload, which `sw.js` reads:

   ```json
   {"title": "Dinner tip", "body": "You're 40 g short on protein today…", "url": "./", "tag": "dinner_tip"}
   ```

   The service worker shows `Zippy · <title>` and opens `url` on tap. Use a same-origin relative URL. Delete a subscription when the push service answers 404 or 410.
5. **Proxy.** The Caddyfile already forwards `/api/push/*` with the server token.

Until these routes exist, **Turn on notifications** reports that it couldn't turn notifications on. Chat, pages and the in-app lock screen work without push.
