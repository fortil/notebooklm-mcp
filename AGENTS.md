# AGENTS.md

Guide for coding agents working in this repo. `nlm-mcp` is an MCP server for Google NotebookLM. README.md covers usage; this file covers how to change the code.

## Commands

```
uv sync --all-extras --dev
uv run ruff check src
uv run mypy src
uv run nlm-mcp --help
```

There is no test suite yet. The check that matters is the end-to-end scenario against `FakeBackend` (an MCP client calling every tool, no Google account needed), plus ruff and mypy.

## Layout

- `src/nlm_mcp/backends/base.py`: the `Backend` protocol. The tool layer only sees this.
- `src/nlm_mcp/backends/notebooklm_py.py`: the only module allowed to import `notebooklm`. Keep it that way; a grep in the checks enforces it.
- `src/nlm_mcp/backends/fake.py`: in-memory backend for development and checks.
- `src/nlm_mcp/tools/`: one module per tool group (notebooks, sources, chat, resources, artifacts).
- `src/nlm_mcp/tenancy.py`, `auth.py`, `config.py`: tenant resolution, bearer-token auth for streamable-http, settings (`NLM_MCP_*` env vars).
- `src/nlm_mcp/errors.py`: every SDK exception becomes `NlmError`, then `ToolError("[CODE] ...")`. Other exceptions lose their message, so convert before raising.

## Rules

- Server code uses `MCPServer` from `mcp>=2.3,<3`. `FastMCP` no longer exists in 2.x and `fastmcp` is not a dependency.
- Auth to Google is delegated to `notebooklm login`. This repo only maps tenant to credentials (`TenantContext` and `BackendFactory`).
- `streamable-http` refuses to start without `NLM_MCP_TOKENS_FILE`. Do not add an unauthenticated network mode.
- `allow_local_files` is forced off for `streamable-http`.
- Every tool call and SDK RPC event goes through `UsageMeter` (JSONL). That is the billing hook; keep new tools wired to it.
- Never commit credentials, cookies, `.auth/`, usage logs or downloaded artifacts.
- Type hints everywhere; ruff and mypy must pass before a change is done.

## Known gaps

- `NotebookLmPyBackend` has not been run against a real account. Unverified: `GenerationStatus.metadata["artifact_id"]`, `report_format == "study_guide"`, the `SourceType` names.
- `doctor` exits with 2, not 0, when the environment is invalid.
- Out of scope for now: Docker, CI, PyPI release, REST bridge, `mind_map`.
