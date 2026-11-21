# Zippy chat API handoff

Use the [Zippy API contracts](../ZIPPY_SPEC.md#5-contracts) for route and card definitions. The backend owns account data, chat history, the Shopee MCP connection, orders, and any S3 access. The frontend displays the response and sends explicit user actions.

## Connect

The chat client defaults to `./api/`. Caddy strips the `/api` prefix before forwarding to `BACKEND_URL` and adds the server-side `API_TOKEN`. Set matching tokens on both deployed servers. If hosting the frontend on S3 later, set the `zippy-api` meta tag to the HTTPS prefix of an authenticated API gateway or frontend proxy. Keep API tokens and AWS credentials out of static files.

The frontend opens with an empty conversation. For live use, configure the backend for the intended user and sources. Backend demo mode can still supply the documented Ploy data. The frontend shows only what the selected backend sends.

## Chat and shopping

1. Accept `POST /chat` with `{session_id, message}`. The browser gives each conversation its own session ID and stores its visible history for the current tab. Return `application/x-ndjson` and finish with a `done` or `error` event. Keep authoritative conversation state on the server.
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

The camera uses `POST /food-log/photo?session_id=…` with multipart `file`. Add the meal summary to the session feed after storage and analysis succeed.

## Integration acceptance

- Submit a question and confirm that streamed text, product cards, and quick replies appear from the API. An empty search must leave the conversation without a product card. An error must offer Retry.
- Review a sandbox product and confirm that the quote uses backend prices. Complete payment only through the hosted provider. Confirm that the receipt appears once, after backend verification.
- Review the selected backend’s source configuration before connecting personal data. Keep account storage and authentication on the server.
