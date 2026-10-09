"""End-to-end check: an MCP client calls every tool against FakeBackend.

Run with:  uv run python scripts/e2e_fake.py

The same file plays two roles. Without arguments it is the client: it spawns
itself as an MCP stdio server (`--serve-fake`) wired to FakeBackendFactory,
then runs the full scenario (16 tools, 2 resources, one error path) over real
JSON-RPC. No Google account is needed.

Exit code 0 = every step passed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

EXPECTED_TOOLS = {
    "list_notebooks",
    "get_notebook",
    "create_notebook",
    "rename_notebook",
    "delete_notebook",
    "list_sources",
    "add_source",
    "get_source",
    "remove_source",
    "search_sources",
    "chat",
    "generate_artifact",
    "get_task",
    "list_artifacts",
    "download_artifact",
    "get_usage",
}


def serve_fake() -> None:
    from nlm_mcp.backends.fake import FakeBackendFactory
    from nlm_mcp.config import Settings
    from nlm_mcp.server import create_server

    settings = Settings.from_env()
    settings.validate_for_serve()
    create_server(settings, factory=FakeBackendFactory()).run("stdio")


def payload(result: object) -> dict:
    structured = getattr(result, "structuredContent", None)
    if structured:
        return dict(structured)
    text = getattr(result, "content", None)
    return json.loads(text[0].text)


async def run_scenario() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    results: list[tuple[bool, str]] = []

    def check(ok: bool, label: str, detail: str = "") -> None:
        results.append((ok, label))
        mark = "ok  " if ok else "FAIL"
        print(f"{mark} {label}{(' — ' + detail) if detail and not ok else ''}")

    tmp = Path(tempfile.mkdtemp(prefix="nlm-mcp-e2e-"))
    downloads = tmp / "downloads"
    usage_log = tmp / "usage.jsonl"
    src_file = tmp / "notes.md"
    src_file.write_text("The quick brown fox jumps over the lazy dog.")

    env = os.environ.copy()
    env.update(
        {
            "NLM_MCP_DOWNLOAD_DIR": str(downloads),
            "NLM_MCP_USAGE_LOG": str(usage_log),
            "NLM_MCP_PROFILE": "fake",
        }
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).resolve()), "--serve-fake"],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = (await session.list_tools()).tools
            names = {t.name for t in tools}
            check(names == EXPECTED_TOOLS, "list_tools reports the 16 tools", str(names))

            delete = next(t for t in tools if t.name == "delete_notebook")
            check(
                bool(delete.annotations and delete.annotations.destructive_hint),
                "delete_notebook is annotated destructive",
            )

            resources = (await session.list_resources()).resources
            uris = {str(r.uri) for r in resources}
            templates = {
                str(t.uri_template)
                for t in (await session.list_resource_templates()).resource_templates
            }
            check(
                "notebooklm://notebooks" in uris and any("sources" in t for t in templates),
                "resources: notebooks + sources template",
                f"uris={uris} templates={templates}",
            )

            nb = payload(await session.call_tool("create_notebook", {"title": "E2E Fake"}))
            nb_id = nb["id"]
            check(bool(nb_id), "create_notebook", json.dumps(nb))

            items = payload(await session.call_tool("list_notebooks", {"query": "e2e"}))["items"]
            check(
                len(items) == 1 and items[0]["title"] == "E2E Fake", "list_notebooks (query filter)"
            )

            detail = payload(
                await session.call_tool(
                    "get_notebook", {"notebook_id": nb_id, "include_summary": True}
                )
            )
            check(detail["summary"] is not None, "get_notebook with summary")

            renamed = payload(
                await session.call_tool(
                    "rename_notebook", {"notebook_id": nb_id, "title": "E2E Renamed"}
                )
            )
            check(renamed["title"] == "E2E Renamed", "rename_notebook")

            s1 = payload(
                await session.call_tool(
                    "add_source",
                    {
                        "notebook_id": nb_id,
                        "kind": "url",
                        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    },
                )
            )
            s2 = payload(
                await session.call_tool(
                    "add_source",
                    {
                        "notebook_id": nb_id,
                        "kind": "text",
                        "title": "Notes",
                        "text": "NotebookLM is a research assistant grounded in your sources.",
                    },
                )
            )
            s3 = payload(
                await session.call_tool(
                    "add_source", {"notebook_id": nb_id, "kind": "file", "path": str(src_file)}
                )
            )
            check(
                all(s.get("id") for s in (s1, s2, s3)),
                "add_source url + text + file",
                json.dumps([s1, s2, s3]),
            )

            sources = payload(await session.call_tool("list_sources", {"notebook_id": nb_id}))[
                "items"
            ]
            check(len(sources) == 3, "list_sources returns 3", str(len(sources)))

            res = await session.read_resource(f"notebooklm://notebooks/{nb_id}/sources")
            res_items = json.loads(res.contents[0].text)["items"]
            check(len(res_items) == 3, "resource sources read", str(len(res_items)))

            full = payload(
                await session.call_tool(
                    "get_source", {"notebook_id": nb_id, "source_id": s2["id"], "fulltext": True}
                )
            )
            check(full["text"] and "research assistant" in full["text"], "get_source with fulltext")

            passages = payload(
                await session.call_tool(
                    "search_sources", {"notebook_id": nb_id, "query": "research"}
                )
            )["items"]
            check(len(passages) >= 1, "search_sources finds a passage", str(len(passages)))

            answer = payload(
                await session.call_tool(
                    "chat", {"notebook_id": nb_id, "question": "What is NotebookLM?"}
                )
            )
            check(
                bool(answer.get("answer"))
                and answer.get("citations")
                and answer.get("conversation_id"),
                "chat returns answer + citations + conversation_id",
                json.dumps(answer),
            )

            task = payload(
                await session.call_tool("generate_artifact", {"notebook_id": nb_id, "kind": "quiz"})
            )
            task_id = task["task_id"]
            check(
                task["state"] == "pending",
                "generate_artifact returns pending task",
                json.dumps(task),
            )

            first = payload(
                await session.call_tool("get_task", {"notebook_id": nb_id, "task_id": task_id})
            )
            check(
                first["state"] == "in_progress",
                "get_task first poll = in_progress",
                json.dumps(first),
            )

            done = payload(
                await session.call_tool("get_task", {"notebook_id": nb_id, "task_id": task_id})
            )
            check(
                done["state"] == "completed" and bool(done["artifact_id"]),
                "get_task second poll = completed",
            )

            artifacts = payload(await session.call_tool("list_artifacts", {"notebook_id": nb_id}))[
                "items"
            ]
            check(
                len(artifacts) == 1 and artifacts[0]["kind"] == "quiz",
                "list_artifacts shows the quiz",
            )

            dl = payload(
                await session.call_tool(
                    "download_artifact", {"notebook_id": nb_id, "artifact_id": done["artifact_id"]}
                )
            )
            dl_path = Path(dl["path"])
            check(
                dl_path.is_file() and dl_path.parent == downloads.resolve(),
                "download_artifact writes file",
                dl["path"],
            )

            usage = payload(await session.call_tool("get_usage", {}))
            check(
                usage["session_ok"] and usage["notebooks_used"] == 1, "get_usage", json.dumps(usage)
            )

            await session.call_tool("remove_source", {"notebook_id": nb_id, "source_id": s1["id"]})
            remaining = payload(await session.call_tool("list_sources", {"notebook_id": nb_id}))[
                "items"
            ]
            check(len(remaining) == 2, "remove_source leaves 2", str(len(remaining)))

            await session.call_tool("delete_notebook", {"notebook_id": nb_id})
            left = payload(await session.call_tool("list_notebooks", {}))["items"]
            check(len(left) == 0, "delete_notebook cleans up", str(len(left)))

            err = await session.call_tool("get_notebook", {"notebook_id": "nb-999"})
            err_text = err.content[0].text if err.content else ""
            check(
                bool(err.is_error) and "[NOT_FOUND]" in err_text,
                "unknown notebook returns [NOT_FOUND]",
                err_text[:120],
            )

    if usage_log.exists():
        lines = [json.loads(line) for line in usage_log.read_text().splitlines()]
        tool_events = {entry.get("tool") for entry in lines}
        missing = EXPECTED_TOOLS - tool_events
        check(not missing, "usage log records every tool", f"missing={missing}")
    else:
        check(False, "usage log exists", str(usage_log))

    passed = sum(1 for ok, _ in results if ok)
    print(f"\nE2E: {passed}/{len(results)} steps passed")
    return 0 if passed == len(results) else 1


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--serve-fake":
        serve_fake()
        return
    sys.exit(asyncio.run(run_scenario()))


if __name__ == "__main__":
    main()
