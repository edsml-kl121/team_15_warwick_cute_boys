# MCP server

The MCP server exposes a `greet` tool that calls the FastAPI backend.

Run `docker compose up --build mcp` from the repository root. Connect an MCP client using Streamable HTTP at `http://localhost:8001/mcp` and call `greet` with `{"name":"Ada"}`. The tool should return `Hello, Ada!`.
