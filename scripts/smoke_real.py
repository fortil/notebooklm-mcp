"""Smoke check of the artifact surface against a real NotebookLM account.

Opt-in: needs a stored session (`uv run nlm-mcp auth login`). Creates a
throwaway notebook, adds one text source, chats, generates and downloads each
requested artifact kind, toggles sharing, then deletes the notebook.

Run with:  uv run python scripts/smoke_real.py [kind ...]

Default kinds: slide_deck data_table infographic mind_map report quiz
Add "video" or "audio_overview" explicitly; they take minutes.
"""

from __future__ import annotations

import asyncio
import sys
import time

from nlm_mcp.backends.base import TenantContext
from nlm_mcp.backends.notebooklm_py import ProfileBackendFactory
from nlm_mcp.errors import NlmError
from nlm_mcp.models import AddSourceRequest, GenerateRequest

DEFAULT_KINDS = ["slide_deck", "data_table", "infographic", "mind_map", "report", "quiz"]
KIND_TIMEOUT = {"video": 600.0, "audio_overview": 720.0}
OPTIONS = {
    "slide_deck": {"format": "presenter_slides", "length": "short"},
    "infographic": {"orientation": "landscape", "style": "professional"},
    "quiz": {"quantity": "fewer", "difficulty": "easy"},
}
DOWNLOAD_FORMAT = {"slide_deck": "pptx"}
# Pseudo-kind: smoke "mind_map_interactive" maps to kind=mind_map + variant.
PSEUDO_KINDS = {"mind_map_interactive": ("mind_map", {"variant": "interactive"})}

TEXT = (
    "The printing press reached Venice in 1469, when John of Speyer received a "
    "five-year monopoly on printing there. His brother Wendelin expanded the trade "
    "and printed close to two hundred editions. Venice offered papermakers, a merchant "
    "network and a patent office, so by 1500 the city housed over a hundred presses, "
    "roughly one seventh of all presses in Europe. Aldus Manutius opened his shop in "
    "1494 and printed small, affordable pocket editions of the classics, inventing "
    "italic type along the way."
)


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[bool, str]] = []

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        self.results.append((ok, label))
        mark = "ok  " if ok else "FAIL"
        print(f"{mark} {label}{(' — ' + detail) if detail and not ok else ''}", flush=True)

    @property
    def failed(self) -> int:
        return sum(1 for ok, _ in self.results if not ok)


async def wait_task(
    backend: object, notebook_id: str, task_id: str, timeout: float
) -> tuple[str, str | None]:
    deadline = time.monotonic() + timeout
    state, artifact_id = "unknown", None
    while time.monotonic() < deadline:
        status = await backend.get_task(notebook_id, task_id)
        state, artifact_id = status.state, status.artifact_id
        if state in ("completed", "failed"):
            return state, artifact_id
        await asyncio.sleep(10)
    return state, artifact_id


async def main() -> int:
    kinds = sys.argv[1:] or DEFAULT_KINDS
    report = Report()
    factory = ProfileBackendFactory(sdk_backend="web", max_concurrent_rpcs=2, on_rpc_event=None)
    backend = await factory.open(TenantContext("local", "default", "web"))
    notebook_id = ""
    try:
        usage = await backend.get_usage()
        windows = {w.kind: round(w.used_percent) for w in usage.windows}
        report.check(usage.session_ok, "get_usage", str(windows))
        print(f"     usage windows: {windows}", flush=True)

        options = await backend.get_artifact_options()
        audio_values = [c.value for c in options.audio]
        deck_values = [c.value for c in options.slide_deck]
        report.check(
            bool(options.slide_deck) or bool(options.audio),
            "get_artifact_options",
            f"audio={audio_values} slide_deck={deck_values}",
        )

        nb = await backend.create_notebook("nlm-mcp smoke 2026-10-15")
        notebook_id = nb.id
        report.check(bool(notebook_id), "create_notebook", notebook_id)

        src = await backend.add_source(
            AddSourceRequest(
                notebook_id=notebook_id,
                kind="text",
                title="Printing in Venice",
                text=TEXT,
                wait=True,
            )
        )
        report.check(src.state == "ready", "add_source text", f"state={src.state}")

        chat = await backend.ask(notebook_id, "Who invented italic type?", None, None)
        report.check("Aldus" in chat.answer, "chat regression", chat.answer[:80])

        share = await backend.set_notebook_public(notebook_id, True, "chat_only")
        report.check(share.is_public, "share_notebook on", str(share.share_url))
        off = await backend.set_notebook_public(notebook_id, False, None)
        report.check(not off.is_public, "share_notebook off")

        for kind in kinds:
            real_kind, extra_opts = PSEUDO_KINDS.get(kind, (kind, {}))
            prompt = "Audience: students." if real_kind == "slide_deck" else "Keep it short."
            try:
                task = await backend.generate_artifact(
                    GenerateRequest(
                        notebook_id=notebook_id,
                        kind=real_kind,  # type: ignore[arg-type]
                        instructions=prompt,
                        language="en",
                        options={**OPTIONS.get(real_kind, {}), **extra_opts},
                    )
                )
            except NlmError as exc:
                report.check(False, f"generate {kind}", exc.to_tool_message())
                continue
            if task.state == "completed":
                state, artifact_id = "completed", task.artifact_id
            else:
                state, artifact_id = await wait_task(
                    backend, notebook_id, task.task_id, KIND_TIMEOUT.get(kind, 300.0)
                )
            report.check(
                state == "completed" and bool(artifact_id),
                f"generate {kind}",
                f"state={state} artifact_id={artifact_id}",
            )
            if not artifact_id:
                continue
            try:
                dl = await backend.download_artifact(
                    notebook_id,
                    artifact_id,
                    f"/tmp/nlm-smoke/{artifact_id}.{DOWNLOAD_FORMAT.get(real_kind, 'x')}",
                    DOWNLOAD_FORMAT.get(real_kind),
                )
                report.check(dl.bytes > 10, f"download {kind}", f"{dl.path} ({dl.bytes} bytes)")
            except NlmError as exc:
                report.check(False, f"download {kind}", exc.to_tool_message())

        artifacts = await backend.list_artifacts(notebook_id)
        by_kind = sorted(a.kind for a in artifacts)
        expected = sorted(PSEUDO_KINDS.get(k, (k, {}))[0] for k in kinds)
        report.check(by_kind == expected, "list_artifacts after run", str(by_kind))
    finally:
        if notebook_id:
            try:
                await backend.delete_notebook(notebook_id)
                report.check(True, "cleanup delete_notebook")
            except NlmError as exc:
                report.check(False, "cleanup delete_notebook", exc.to_tool_message())
        await factory.close()

    total = len(report.results)
    print(f"\nSMOKE: {total - report.failed}/{total} steps passed", flush=True)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
