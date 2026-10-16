# AGENTS.md

Guide for coding agents working in this repo. `nlm-mcp` is an MCP server for Google NotebookLM. README.md covers usage; this file covers how to change the code.

## Commands

```
uv sync --all-extras --dev
uv run ruff check src
uv run mypy src
uv run nlm-mcp --help
```

There is no test suite yet. The check that matters is the end-to-end scenario against `FakeBackend` (`uv run python scripts/e2e_fake.py`: an MCP client calling every tool, no Google account needed), plus ruff and mypy. `scripts/smoke_real.py` is the opt-in check against a real account; it needs a stored session and spends generation quota.

## Layout

- `src/nlm_mcp/backends/base.py`: the `Backend` protocol. The tool layer only sees this.
- `src/nlm_mcp/backends/notebooklm_py.py`: the only module allowed to import `notebooklm`. Keep it that way; a grep in the checks enforces it.
- `src/nlm_mcp/backends/fake.py`: in-memory backend for development and checks.
- `src/nlm_mcp/tools/`: one module per tool group (notebooks, sources, chat, artifacts, sharing, resources).
- `src/nlm_mcp/models.py`: every Literal that defines the wire contract (`ArtifactKind`, `GENERATABLE_KINDS`, share levels). The tool schemas and the backend dispatch both derive from them; change them there, nowhere else.
- `src/nlm_mcp/tenancy.py`, `auth.py`, `config.py`: tenant resolution, bearer-token auth for streamable-http, settings (`NLM_MCP_*` env vars).
- `src/nlm_mcp/errors.py`: every SDK exception becomes `NlmError`, then `ToolError("[CODE] ...")`. Other exceptions lose their message, so convert before raising.

## Rules

- Server code uses `MCPServer` from `mcp>=2.3,<3`. `FastMCP` no longer exists in 2.x and `fastmcp` is not a dependency.
- Auth to Google is delegated to `notebooklm login`. This repo only maps tenant to credentials (`TenantContext` and `BackendFactory`).
- `streamable-http` refuses to start without `NLM_MCP_TOKENS_FILE`. Do not add an unauthenticated network mode.
- `allow_local_files` is forced off for `streamable-http`.
- Every tool call and SDK RPC event goes through `UsageMeter` (JSONL). That is the billing hook; keep new tools wired to it.
- `generate_artifact` never substitutes a kind: unknown kinds or options fail with the valid values listed. Keep it that way when adding kinds.
- Never commit credentials, cookies, `.auth/`, usage logs or downloaded artifacts.
- Type hints everywhere; ruff and mypy must pass before a change is done.

## Known gaps

- Verified against a real account on 2026-10-15 (`scripts/smoke_real.py`): notebooks, text sources, chat, sharing, `get_artifact_options`, and generate + poll + list + download of every kind (slide_deck as pptx, data_table, infographic, mind_map in both variants, report, study_guide, quiz, flashcards, video, audio_overview). `GenerationStatus` carries no `metadata["artifact_id"]`; task_id and artifact_id are the same id, and `_task()` relies on that.
- Not yet exercised for real: url/file/drive sources on the current pin, download formats other than the smoke defaults (quiz markdown/html, slide_deck pdf), the report/blog_post, concept_explanation and custom formats, video styles beyond the default.
- A note-backed mind map came back in Spanish on an account with Spanish output settings even with `language="en"`; the account-level output language may win. Unconfirmed.
- `doctor` exits with 2, not 0, when the environment is invalid.
- `notebooklm-py` is pinned to commit `2aff0fc` on its `main` branch, because 0.8.4 saves an empty session on fresh logins (teng-lin/notebooklm-py#2478). Switch back to `notebooklm-py[headless]>=0.8.5,<0.9` when that release ships; the git pin blocks a PyPI upload.
- `auth login --durable` (master token through Google's EmbeddedSetup page) has not been tried against a real account.
- Out of scope for now: Docker, CI, PyPI release, REST bridge. The README "Coverage" section lists the SDK services the server does not expose (notes, research, per-user sharing, and the rest).
