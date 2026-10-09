<p align="center">
  <img src=".github/assets/logo.svg" width="150" alt="nlm-mcp logo: a spiral notebook with Google-colored sparkles">
</p>

# nlm-mcp

<p align="center">
  <a href="https://github.com/fortil/nlm-mcp"><img src="https://img.shields.io/badge/github-fortil%2Fnlm--mcp-181717?logo=github" alt="github.com/fortil/nlm-mcp"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license MIT">
  <img src="https://img.shields.io/badge/MCP-server-5F45AF" alt="MCP server">
  <img src="https://img.shields.io/badge/uv-ready-de5fe9?logo=uv" alt="uv">
</p>

An MCP server for Google NotebookLM (now branded "Gemini Notebook"). It exposes 16 tools and 2 resources for notebooks, sources, grounded chat and generated artifacts. It talks to Google through the unofficial `notebooklm-py` client, which calls private endpoints. Google's terms of service may not allow that kind of access, so use it with an account you can afford to lose.

The tool layer never touches the SDK. All SDK code sits in `src/nlm_mcp/backends/notebooklm_py.py`, behind a `Backend` protocol, and a `FakeBackend` runs the whole tool surface without a Google account.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Install

```
git clone https://github.com/fortil/nlm-mcp.git
cd nlm-mcp
uv sync --extra browser
```

## First login

```
uv run nlm-mcp auth login -- --browser chrome
```

Sessions are stored per profile in `~/.notebooklm/profiles/<profile>/storage_state.json` (override the root with `NOTEBOOKLM_HOME`).

Authentication is delegated to the `notebooklm` CLI that ships with `notebooklm-py`:

- `nlm-mcp auth login` runs `notebooklm login` for the selected profile and ends with a compact verdict on the saved session, so a broken capture (missing `SID` or `__Secure-1PSIDTS`) exits 1 instead of passing silently.
- `nlm-mcp auth status` prints a compact local check of the saved session: cookies present, account, storage path. `--test` also fetches a live token from Google, `--raw` shows the SDK's own output instead.

Arguments after `--` are passed through unchanged. `nlm-mcp doctor` prints the resolved settings and whether the session file exists.

## Client configuration

The same block works for Claude Desktop, Claude Code (`.mcp.json`) and Cursor (`.cursor/mcp.json`). Replace the path.

```json
{
  "mcpServers": {
    "notebooklm": {
      "command": "uv",
      "args": ["run", "--directory", "/ABS/PATH/notebooklm-mcp", "nlm-mcp", "serve"],
      "env": { "NLM_MCP_PROFILE": "default" }
    }
  }
}
```

## Tools

| Tool | What it does | Annotation |
|---|---|---|
| `list_notebooks` | List notebooks, optional title filter | read-only |
| `get_notebook` | One notebook, optionally with its summary | read-only |
| `create_notebook` | Create a notebook (not idempotent upstream) | mutating |
| `rename_notebook` | Rename a notebook | idempotent |
| `delete_notebook` | Delete a notebook | destructive |
| `list_sources` | List sources, optional state filter | read-only |
| `add_source` | Add a url, text, file or drive source | mutating |
| `get_source` | Source metadata, optionally full text | read-only |
| `remove_source` | Delete a source | destructive |
| `search_sources` | Search passages inside a notebook | read-only |
| `chat` | Ask a question grounded in the sources | read-only |
| `generate_artifact` | Start audio overview, report, study guide, quiz or flashcards; returns a task id | mutating |
| `get_task` | State of a generation task | read-only |
| `list_artifacts` | List generated artifacts | read-only |
| `download_artifact` | Save an artifact under the download directory | mutating |
| `get_usage` | Account limits, usage windows, session state | read-only |

Resources: `notebooklm://notebooks` and `notebooklm://notebooks/{notebook_id}/sources`.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `NLM_MCP_PROFILE` | `$NOTEBOOKLM_PROFILE` or `default` | SDK profile |
| `NLM_MCP_BACKEND` | `web` | `web` or `android` |
| `NLM_MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `NLM_MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `NLM_MCP_PORT` | `8765` | HTTP port |
| `NLM_MCP_TOOLS` | all | Comma-separated tool allowlist |
| `NLM_MCP_DOWNLOAD_DIR` | `~/.nlm-mcp/downloads` | Sandbox for `download_artifact` |
| `NLM_MCP_ALLOW_LOCAL_FILES` | true on stdio, false on HTTP | Allow `add_source` with `kind=file` |
| `NLM_MCP_MAX_CONCURRENT_RPCS` | `4` | Concurrent SDK calls |
| `NLM_MCP_USAGE_LOG` | unset | JSONL file for usage events |
| `NLM_MCP_LOG_LEVEL` | `WARNING` | stderr log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `NLM_MCP_TOKENS_FILE` | unset | Bearer token to tenant map, required for HTTP |

## Errors

Tool errors start with a code in brackets.

| Code | Meaning |
|---|---|
| `AUTH_REQUIRED` | No valid session; run `notebooklm login` |
| `RATE_LIMITED` | Google throttled the request; retryable |
| `QUOTA_EXCEEDED` | Notebook or source limit reached |
| `NOT_FOUND` | Unknown notebook, source or artifact |
| `TIMEOUT` | The wait ran out; the operation may still finish |
| `UNSUPPORTED` | Disabled or unavailable operation |
| `INVALID_ARGUMENT` | Bad parameters |
| `TRANSIENT` | Network problem or unsafe-to-retry call |
| `UPSTREAM` | Any other failure from Google or the SDK |

## Running as a shared server

```
NLM_MCP_TRANSPORT=streamable-http \
NLM_MCP_TOKENS_FILE=/etc/nlm-mcp/tokens.json \
NLM_MCP_USAGE_LOG=/var/log/nlm-mcp/usage.jsonl \
uv run nlm-mcp serve
```

The server refuses to start without `NLM_MCP_TOKENS_FILE`. The file maps bearer tokens to tenants:

```json
{ "tok-abc": { "tenant_id": "acme", "profile": "acme-prof" } }
```

Each tool call appends one line to the `NLM_MCP_USAGE_LOG` file with `ts`, `tenant_id`, `tool`, `ok`, `elapsed_ms` and `error_code`. SDK calls are logged too, with the tool name `rpc:<method>`. That file is the metering feed.

Two seams to replace for a paid multi-tenant deployment: `BackendFactory` (where credentials come from) and `UsageMeter` (where usage events go, for billing).

## Known limits

- Google rate-limits the private endpoints; the SDK retries 429 and 5xx responses with backoff.
- `create_notebook` is not idempotent. After an error, call `list_notebooks` with the title before retrying.
- A `TIMEOUT` does not mean the operation failed; check with `get_task` or `list_artifacts`.
- Free accounts have low notebook, source and generation quotas. `get_usage` shows them.
- Sessions expire; run `nlm-mcp auth login` again when you see `AUTH_REQUIRED`.

## Roadmap

Mind maps, video and slide decks, an enterprise Discovery Engine adapter, a Docker image, a PyPI release.

## Maintainer

William, [@fortil](https://github.com/fortil).
