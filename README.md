<p align="center">
  <img src=".github/assets/logo.svg" width="150" alt="notebooklm-mcp logo: a spiral notebook with Google-colored sparkles">
</p>

# notebooklm-mcp

<p align="center">
  <a href="https://github.com/fortil/notebooklm-mcp"><img src="https://img.shields.io/badge/github-fortil%2Fnotebooklm--mcp-181717?logo=github" alt="github.com/fortil/notebooklm-mcp"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license MIT">
  <img src="https://img.shields.io/badge/MCP-server-5F45AF" alt="MCP server">
  <img src="https://img.shields.io/badge/uv-ready-de5fe9?logo=uv" alt="uv">
</p>

An MCP server for Google NotebookLM (now branded "Gemini Notebook"). It exposes 19 tools and 2 resources for notebooks, sources, grounded chat, generated artifacts and notebook sharing. Every artifact type the NotebookLM Studio can create works here: audio overview, report, study guide, quiz, flashcards, video overview, mind map, infographic, slide deck and data table. The server talks to Google through the unofficial `notebooklm-py` client, which calls private endpoints. Google's terms of service may not allow that kind of access, so use it with an account you can afford to lose. The repo is named `notebooklm-mcp`; the command it installs is `nlm-mcp`.

The tool layer never touches the SDK. All SDK code sits in `src/nlm_mcp/backends/notebooklm_py.py`, behind a `Backend` protocol, and a `FakeBackend` runs the whole tool surface without a Google account.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Install

```
git clone https://github.com/fortil/notebooklm-mcp.git
cd notebooklm-mcp
uv sync --extra browser
```

## First login

```
uv run nlm-mcp auth login -- --browser chrome
```

A Chrome window opens on Google's sign-in page. Sign in, and the command ends with a verdict: `session ok` plus your account email, or `session broken` with exit code 1. The verdict comes from a live token fetch, so a session that only looks complete on disk still fails here. Without Chrome installed, drop `-- --browser chrome` and run `uv run playwright install chromium` once to use the bundled browser.

Sessions are stored per profile in `~/.notebooklm/profiles/<profile>/storage_state.json` (override the root with `NOTEBOOKLM_HOME`).

### Cookies expire

Google session cookies last days to weeks. When tools start failing with `AUTH_REQUIRED`, run `auth login` again. To skip that, log in once in durable mode:

```
uv run nlm-mcp auth login --durable --account you@gmail.com -- --browser chrome
```

This saves a Google master token next to the session, and the SDK uses it to get fresh cookies when the old ones expire. `auth status` shows `renewal automatic` when it is in place. The master token gives full access to the Google account and is stored with mode 0600. Do not use durable mode on a shared machine.

### Other auth commands

- `nlm-mcp auth status` prints the saved session: cookies, account, storage path and renewal mode. `--test` also fetches a live token from Google, `--raw` shows the SDK's own output.
- `nlm-mcp doctor` prints the resolved settings and whether the session file exists.
- Arguments after `--` go to `notebooklm login` unchanged.

### When login fails

- `session broken` with only `NID` and `__Host-GAPS` captured: the profile holds a stale anonymous session. Run `uv run nlm-mcp auth login --fresh -- --browser chrome`.
- Google says the browser may not be secure: use `-- --browser chrome` (your installed Chrome) instead of the bundled Chromium.
- No browser window works at all: sign in at https://notebook.google.com in Firefox, then `uv sync --extra cookies` and `uv run notebooklm login --browser-cookies firefox`. Importing from Chrome also works, but on macOS the terminal needs Full Disk Access to read Chrome's cookies, and on Windows Chrome 127+ blocks it.

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
| `generate_artifact` | Start any of the 10 artifact types; returns a task id | mutating |
| `get_task` | State of a generation task | read-only |
| `list_artifacts` | List generated artifacts, optional kind filter | read-only |
| `download_artifact` | Save an artifact under the download directory | mutating |
| `get_artifact_options` | The option tables this account accepts (formats, presets) | read-only |
| `get_share_status` | How a notebook is shared today | read-only |
| `share_notebook` | Turn the public link on or off, set what viewers see | idempotent |
| `get_usage` | Account limits, usage windows, session state | read-only |

Resources: `notebooklm://notebooks` and `notebooklm://notebooks/{notebook_id}/sources`.

## Coverage

This table is the source of truth for what the server supports. "Internal RPC" is the batchexecute method id the SDK sends, with the real Google method it resolves to. The SDK ships the full map in `notebooklm/rpc/_identifiers.py`.

### Artifacts

| Artifact | Generate | Download | Options (`options` dict) |
|---|---|---|---|
| `audio_overview` | yes | m4a | `format`: deep_dive, brief, critique, debate; `length`: short, default, long |
| `report` | yes | md | `format`: briefing_doc, blog_post, concept_explanation, custom; `custom_prompt` (custom only) |
| `study_guide` | yes | md | none |
| `quiz` | yes | json, markdown, html | `quantity`: fewer, standard, more; `difficulty`: easy, medium, hard |
| `flashcards` | yes | json, markdown, html | `quantity`: fewer, standard, more; `difficulty`: easy, medium, hard |
| `video` | yes | mp4 | `format`: explainer, brief, cinematic, short; `style`: auto_select, custom, classic, whiteboard, kawaii, anime, watercolor, retro_print, heritage, paper_craft; `style_prompt` (requires `style=custom`; never with cinematic or short) |
| `mind_map` | yes | json | `variant`: note_backed (default) or interactive |
| `infographic` | yes | png | `orientation`: landscape, portrait, square; `detail`: concise, standard, detailed; `style`: auto_select, sketch_note, professional, bento_grid, editorial, instructional, bricks, clay, anime, kawaii, scientific |
| `slide_deck` | yes | pdf, pptx | `format`: detailed_deck, presenter_slides; `length`: default, short |
| `data_table` | yes | csv | none |

Notes on generation:

- All studio artifacts (everything except note-backed mind maps) go through one endpoint: `R7cb6c` -> `LabsTailwindOrchestrationService.CreateArtifact`. Listing is `gArtLc` -> ListArtifacts. The kind and its options travel in the creation payload.
- `mind_map` with `variant=note_backed` uses `yyryJe` -> ActOnSources and is synchronous: the call returns the finished tree and the tool answers `state=completed` with the `artifact_id` right away. `variant=interactive` is a regular CreateArtifact task you poll with `get_task`.
- For `slide_deck`, the audience field of the Studio dialog has no dedicated API parameter; pass it in `instructions`.
- A `kind` or option the server does not know is rejected with the list of valid values. Nothing is ever silently generated as another type.

### Platform services

| Service | Status | Internal RPC |
|---|---|---|
| List notebooks | yes | `wXbhsf` -> ListRecentlyViewedProjects |
| Create / rename / delete notebook | yes | `CCqFvf` CreateProject, `s0tc2d` MutateProject, `WWINqb` DeleteProjects |
| Get notebook + summary | yes | `rLM1Ne` GetProject, `VfAZjd` GenerateNotebookGuide |
| Add source (url, text, file, drive) | yes | `izAoDd` AddSources (files stage through the upload endpoint first) |
| List / read source | yes | via GetProject rows, `hizoJc` LoadSource |
| Delete source | yes | `tGMBJ` DeleteSources |
| Search passages | yes | `ASU5Oe` RetrieveRelevantChunks |
| Grounded chat (with or without source subset) | yes | chat conversation stream |
| Generate / poll / list / download artifacts | yes | `R7cb6c` CreateArtifact, `gArtLc` ListArtifacts, signed asset URLs |
| Artifact option tables | yes | `sqTeoe` GetArtifactCustomizationChoices |
| Public link sharing (on/off, viewer level) | yes | `QDyure` ShareProject, `JFMDGd` GetProjectDetails |
| Account limits and usage windows | yes | `SatQRc` GetAccount, `EylDcb` ListQuotaSummary |

### Supported by the SDK, not exposed here

These work in `notebooklm-py` today; the server does not wrap them yet. None of them is blocked by Google: they are scope decisions, and each can be added behind the same `Backend` protocol.

- Notes (create, update, delete; `client.notes`). Saved chat answers and manual notes. Not requested so far.
- Discover sources and Deep Research (`client.research`: start, poll, cancel, import). A separate job workflow that adds sources from web research.
- Sharing with specific users (add, update, remove by email). Only the public link is exposed; per-user invites involve notification semantics this server has no UI for.
- Suggested questions and next steps (`otmP3b`, `OcvKNc`).
- Export an artifact to Google Drive (`Krh3pd` ExportToDrive); `download_artifact` covers local files.
- Artifact management beyond create/list/download: rename, delete, copy between notebooks, retry a failed generation (`Rytqqe`), revise a single slide (`KmcKPe` DeriveArtifact).
- Labels and collections, notebook copy, chat history listing and cancel.
- `fantasy_map`: NotebookLM lists it on some accounts and the SDK can read it, but there is no generation call to wire, so no `kind` exists for it.

## Tool reference

Arguments shown as JSON for `session.call_tool(name, args)`.

### list_notebooks

Read-only. Optional `query` filters by title substring.

```json
{"query": "thesis"}
```

### get_notebook

Read-only. `include_summary: true` adds the notebook guide summary.

```json
{"notebook_id": "abc", "include_summary": true}
```

### create_notebook

Creates a notebook titled `title`. Not idempotent upstream: after an error, check with `list_notebooks` before retrying.

```json
{"title": "Research"}
```

### rename_notebook / delete_notebook

`rename_notebook` takes `notebook_id` and `title`. `delete_notebook` takes `notebook_id` and is destructive.

```json
{"notebook_id": "abc", "title": "Research 2"}
```

### add_source

Adds a source. `kind` is `url`, `text`, `file` or `drive`; each kind needs its field (`url`, `text` plus optional `title`, local `path`, or `drive_document_id`). `wait: true` blocks until NotebookLM finishes ingesting (up to 120 s); default returns the source in `processing` state. `file` is refused on streamable-http unless `NLM_MCP_ALLOW_LOCAL_FILES` was enabled.

```json
{"notebook_id": "abc", "kind": "text", "title": "Notes", "text": "..."}
```

### list_sources / get_source / remove_source

`list_sources` filters by optional `state` (preparing, processing, ready, error). `get_source` with `fulltext: true` returns the whole text (truncated flag included). `remove_source` is destructive.

```json
{"notebook_id": "abc", "state": "ready"}
```

### search_sources

Read-only. Ranked passages (`source_id`, `text`, `rank`) for a `query`, optional `limit`.

```json
{"notebook_id": "abc", "query": "sampling method", "limit": 10}
```

### chat

Read-only. Asks `question` grounded in the sources. Optional `source_ids` restricts the grounding; optional `conversation_id` (from a previous answer) continues that thread. Returns the answer, citations and the conversation id.

```json
{"notebook_id": "abc", "question": "What method did they use?", "conversation_id": "conv-1"}
```

### generate_artifact

Starts generation of `kind`: `audio_overview`, `report`, `study_guide`, `quiz`, `flashcards`, `video`, `mind_map`, `infographic`, `slide_deck` or `data_table`. Accepted `options` per kind are in the coverage table. `source_ids` defaults to every source in the notebook. `instructions` is free text; for slide decks it carries the audience. `language` is an en-style code.

Returns a `task_id` to poll with `get_task`; audio takes minutes and video longer. The exception is `mind_map` with `variant=note_backed`, which finishes inside the call and returns `state=completed` plus `artifact_id`. An unknown `kind` or option fails with the valid values listed; the server never substitutes another artifact type.

```json
{
  "notebook_id": "abc",
  "kind": "slide_deck",
  "instructions": "Audience: data engineers new to the topic",
  "language": "en",
  "options": {"format": "presenter_slides", "length": "short"}
}
```

### get_task

Read-only. State of one task: pending, in_progress, completed (with `artifact_id`), failed (with `error`) or not_found. Poll every 15-30 s.

```json
{"notebook_id": "abc", "task_id": "task-1"}
```

### list_artifacts

Read-only. Artifacts of a notebook with id, kind, state and creation time. Optional `kind` filter accepts every type in the coverage table.

```json
{"notebook_id": "abc", "kind": "slide_deck"}
```

### download_artifact

Saves a completed artifact under `NLM_MCP_DOWNLOAD_DIR` (optional `dest_dir` inside it). The file extension follows the kind; `format` picks between formats for the kinds that have more than one (`slide_deck`: pdf or pptx; `quiz` and `flashcards`: json, markdown or html).

```json
{"notebook_id": "abc", "artifact_id": "art-1", "format": "pptx"}
```

### get_artifact_options

Read-only, account-level. The Studio "Customize" tables this account offers: audio, video and slide deck formats plus report presets, each with the value `generate_artifact` expects. `notebook_id` is optional (the server ignores it).

```json
{}
```

### get_share_status

Read-only. Whether the public link is on, the share URL, what viewers can access (`full_notebook` or `chat_only`) and the users the notebook is shared with.

```json
{"notebook_id": "abc"}
```

### share_notebook

Idempotent. `public: true` turns the link on (response carries the URL); `public: false` removes it. Optional `view_level` sets what viewers see.

```json
{"notebook_id": "abc", "public": true, "view_level": "chat_only"}
```

### get_usage

Read-only. Notebooks used against the account limit, source limit, five-hour and weekly usage windows, and whether the session is valid.

```json
{}
```

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

Tool errors start with a code in brackets. Argument validation (an unknown `kind`, an option the kind does not take) is rejected by the schema check before the tool runs, with the list of valid values in the message.

| Code | Meaning |
|---|---|
| `AUTH_REQUIRED` | No valid session; run `nlm-mcp auth login` |
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
- Sessions expire. Run `nlm-mcp auth login` again when you see `AUTH_REQUIRED`, or use `--durable` once (see "Cookies expire").
- Generation is asynchronous except for note-backed mind maps. Audio takes minutes; video takes longer.

## Roadmap

Notes and Deep Research tools, an enterprise Discovery Engine adapter, a Docker image, a PyPI release.

## Maintainer

William, [@fortil](https://github.com/fortil).
