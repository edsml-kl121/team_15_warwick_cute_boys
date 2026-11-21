# Repository guide

## Zippy

Zippy is a chat-first proactive health assistant. The demo follows Ploy from a sleep insight and a Shopee Mall purchase in the morning to a dinner suggestion, a walk and a phone reservation in the evening.

- **Demo and scope.** Read [the demo script](ZIPPY_SPEC.md#1-the-demo) before changing user-facing behavior. Use it as the acceptance test and ask before changing it. Follow [the build order](ZIPPY_SPEC.md#6-build-order).
- **Integration.** Read [the contracts](ZIPPY_SPEC.md#5-contracts) before changing routes, streams, cards, tools or prompts. Build cards from tool results. Edit agent instructions in the backend YAML and validate prompt placeholders at startup.
- **Chat frontend handoff.** Read [FE/CHAT_API.md](FE/CHAT_API.md) when wiring the chat stream, Shopee checkout, or transcription.
- **Payments and calls.** Ploy approves every payment on the simulator's ShopeePay PIN page. Zippy only requests payment. Use Shopee Food for listings and Twilio for table reservations. Use only verified team test numbers for live calls. Read [the safety rules](ZIPPY_SPEC.md#10-safety-rules) before exercising these flows.
- **Verification.** Keep external dependencies injectable and cover behavior changes with focused, offline tests. See [the test plan](ZIPPY_SPEC.md#8-testing).

## Where to work

- Frontend changes belong in `FE/`. Keep frontend setup and run commands in [FE/README.md](FE/README.md).
- Backend changes belong in `BE/`. Keep backend setup and run commands in [BE/README.md](BE/README.md).
- Model Context Protocol changes belong in `MCP/`. Keep MCP setup and run commands in [MCP/README.md](MCP/README.md).
- Reusable agent workflows live in `.agents/skills/`. Read the relevant `SKILL.md` when using a workflow.

## Verify changes

- Use the affected component's README and build configuration to find its checks. When you add a runnable component, record its setup, run, and verification commands in its README.
- When changing a shared interface, check its callers and run the relevant checks on each affected component.
- Report which checks ran and which were unavailable.
