# Repository guide

## Where to work

- Frontend changes belong in `FE/`. Keep frontend setup and run commands in [FE/README.md](FE/README.md).
- Backend changes belong in `BE/`. Keep backend setup and run commands in [BE/README.md](BE/README.md).
- Model Context Protocol changes belong in `MCP/`. Keep MCP setup and run commands in [MCP/README.md](MCP/README.md).
- Reusable agent workflows live in `.agents/skills/`. Read the relevant `SKILL.md` when using a workflow.

## Verify changes

- Use the affected component's README and build configuration to find its checks. When you add a runnable component, record its setup, run, and verification commands in its README.
- When changing a shared interface, check its callers and run the relevant checks on each affected component.
- Report which checks ran and which were unavailable.
