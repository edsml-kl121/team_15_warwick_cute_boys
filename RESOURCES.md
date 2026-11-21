# Zippy implementation resources

## Knowledge

- [Zippy build spec](ZIPPY_SPEC.md#1-the-demo) records Ploy’s walkthrough, the API contracts and the intended build order. Use it to understand the purpose of each flow.
- [Chat API handoff](FE/CHAT_API.md#chat-and-shopping) documents the request payload, event shapes, session handling and checkout handoff. Use it when crossing from the browser to FastAPI.
- [Backend service](BE/service.py) is the primary source for business rules. Find `Zippy.chat`, `Zippy.emit` and `Zippy.order_status` to follow the branches in the lesson.
- [Recommendation data and agents](BE/recommendations.py) shows the exact S3 keys, persona lookup, cache, and the branch between food and item recommendations.
- [Guest storage implementation](BE/storage.py) shows how the application selects MongoDB or JSON for a visitor and how recommendation reads query a single guest ID.
- [Recommendation architecture](reference/recommendation-agent-architecture.html) maps the presenter request, two candidate-selection branches, Shopee calls, and chat delivery to their source files.
- [Backend storage and presenter setup](BE/README.md#guest-storage-on-railway) lists the Railway bucket references that feed the S3 client. The presenter section explains the two agent triggers.
- [Backend scenario tests](BE/tests/test_zippy.py) show how the demo can be exercised with fake providers. Start at `test_sleep_and_checkout`.
- [Browser stream tests](FE/tests/services.test.cjs) cover split NDJSON lines, card prices from the API and interrupted streams.
- The repository’s Git history records the actual build sequence. Run `git log --first-parent --reverse --oneline` to compare it with the plan.
