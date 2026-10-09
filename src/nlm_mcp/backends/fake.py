"""In-memory backend used for tests and offline verification."""

from __future__ import annotations

import os

from nlm_mcp.backends.base import Backend, TenantContext
from nlm_mcp.errors import not_found
from nlm_mcp.models import (
    AddSourceRequest,
    Artifact,
    ArtifactKindAny,
    ChatAnswer,
    Citation,
    DownloadedFile,
    GenerateRequest,
    Notebook,
    Passage,
    Source,
    SourceState,
    TaskStatus,
    Usage,
)


class FakeBackend:
    def __init__(self) -> None:
        self.notebooks: dict[str, Notebook] = {}
        self.sources: dict[str, dict[str, Source]] = {}
        self.texts: dict[str, str] = {}
        self.tasks: dict[str, TaskStatus] = {}
        self.task_polls: dict[str, int] = {}
        self.task_artifacts: dict[str, str] = {}
        self.artifacts: dict[str, dict[str, Artifact]] = {}
        self._counters: dict[str, int] = {"nb": 0, "src": 0, "task": 0, "art": 0}

    def _next(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}-{self._counters[prefix]}"

    def _nb(self, notebook_id: str) -> Notebook:
        nb = self.notebooks.get(notebook_id)
        if nb is None:
            raise not_found("notebook", notebook_id)
        return nb

    def _refresh_count(self, notebook_id: str) -> None:
        nb = self.notebooks[notebook_id]
        self.notebooks[notebook_id] = nb.model_copy(
            update={"source_count": len(self.sources[notebook_id])}
        )

    async def list_notebooks(self) -> list[Notebook]:
        return list(self.notebooks.values())

    async def get_notebook(self, notebook_id: str) -> Notebook:
        return self._nb(notebook_id)

    async def get_notebook_summary(self, notebook_id: str) -> str | None:
        self._nb(notebook_id)
        return f"Fake summary of {notebook_id}"

    async def create_notebook(self, title: str) -> Notebook:
        nid = self._next("nb")
        nb = Notebook(
            id=nid,
            title=title,
            source_count=0,
            created_at=None,
            modified_at=None,
            is_owner=True,
        )
        self.notebooks[nid] = nb
        self.sources[nid] = {}
        self.artifacts[nid] = {}
        return nb

    async def rename_notebook(self, notebook_id: str, title: str) -> Notebook:
        nb = self._nb(notebook_id).model_copy(update={"title": title})
        self.notebooks[notebook_id] = nb
        return nb

    async def delete_notebook(self, notebook_id: str) -> None:
        self._nb(notebook_id)
        del self.notebooks[notebook_id]
        self.sources.pop(notebook_id, None)
        self.artifacts.pop(notebook_id, None)

    async def list_sources(
        self, notebook_id: str, state: SourceState | None = None
    ) -> list[Source]:
        self._nb(notebook_id)
        items = list(self.sources[notebook_id].values())
        if state is not None:
            items = [s for s in items if s.state == state]
        return items

    async def get_source(self, notebook_id: str, source_id: str) -> Source:
        self._nb(notebook_id)
        src = self.sources[notebook_id].get(source_id)
        if src is None:
            raise not_found("source", source_id)
        return src

    async def get_source_text(self, notebook_id: str, source_id: str) -> str:
        await self.get_source(notebook_id, source_id)
        return self.texts.get(source_id, "")

    async def add_source(self, req: AddSourceRequest) -> Source:
        self._nb(req.notebook_id)
        sid = self._next("src")
        text = req.text if req.kind == "text" else f"fake content of {req.url or req.path or ''}"
        src = Source(
            id=sid,
            notebook_id=req.notebook_id,
            title=req.title,
            kind=req.kind,
            state="ready",
            url=req.url,
            word_count=len((text or "").split()),
            created_at=None,
        )
        self.sources[req.notebook_id][sid] = src
        self.texts[sid] = text or ""
        self._refresh_count(req.notebook_id)
        return src

    async def remove_source(self, notebook_id: str, source_id: str) -> None:
        await self.get_source(notebook_id, source_id)
        del self.sources[notebook_id][source_id]
        self.texts.pop(source_id, None)
        self._refresh_count(notebook_id)

    async def search_sources(self, notebook_id: str, query: str, limit: int) -> list[Passage]:
        self._nb(notebook_id)
        q = query.lower()
        out: list[Passage] = []
        for sid in self.sources[notebook_id]:
            text = self.texts.get(sid, "")
            if q in text.lower():
                out.append(Passage(source_id=sid, text=text, rank=len(out) + 1))
        return out[:limit]

    async def ask(
        self,
        notebook_id: str,
        question: str,
        source_ids: list[str] | None,
        conversation_id: str | None,
    ) -> ChatAnswer:
        self._nb(notebook_id)
        first = next(iter(self.sources[notebook_id]), "none")
        return ChatAnswer(
            answer=f"fake answer to: {question}",
            conversation_id=conversation_id or "conv-1",
            turn_number=1,
            citations=[Citation(source_id=first, number=1, text="…")],
        )

    async def generate_artifact(self, req: GenerateRequest) -> TaskStatus:
        self._nb(req.notebook_id)
        tid = self._next("task")
        aid = self._next("art")
        status = TaskStatus(task_id=tid, state="pending", artifact_id=None, error=None)
        self.tasks[tid] = status
        self.task_polls[tid] = 0
        self.task_artifacts[tid] = aid
        self.artifacts[req.notebook_id][aid] = Artifact(
            id=aid,
            notebook_id=req.notebook_id,
            title=f"Fake {req.kind}",
            kind=req.kind,
            state="completed",
            created_at=None,
            url=None,
        )
        return status

    async def get_task(self, notebook_id: str, task_id: str) -> TaskStatus:
        self._nb(notebook_id)
        if task_id not in self.tasks:
            raise not_found("task", task_id)
        self.task_polls[task_id] += 1
        if self.task_polls[task_id] == 1:
            st = TaskStatus(task_id=task_id, state="in_progress", artifact_id=None, error=None)
        else:
            st = TaskStatus(
                task_id=task_id,
                state="completed",
                artifact_id=self.task_artifacts[task_id],
                error=None,
            )
        self.tasks[task_id] = st
        return st

    async def list_artifacts(
        self, notebook_id: str, kind: ArtifactKindAny | None = None
    ) -> list[Artifact]:
        self._nb(notebook_id)
        items = list(self.artifacts[notebook_id].values())
        if kind is not None:
            items = [a for a in items if a.kind == kind]
        return items

    async def download_artifact(
        self, notebook_id: str, artifact_id: str, dest_path: str
    ) -> DownloadedFile:
        self._nb(notebook_id)
        if artifact_id not in self.artifacts[notebook_id]:
            raise not_found("artifact", artifact_id)
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake")
        return DownloadedFile(artifact_id=artifact_id, path=dest_path, bytes=4)

    async def get_usage(self) -> Usage:
        return Usage(
            tenant_id="fake",
            notebooks_used=len(self.notebooks),
            notebook_limit=100,
            source_limit=50,
            windows=[],
            session_ok=True,
        )

    async def close(self) -> None:
        return None


class FakeBackendFactory:
    def __init__(self, backend: FakeBackend | None = None) -> None:
        self.backend = backend or FakeBackend()
        self.opened: list[TenantContext] = []

    async def open(self, tenant: TenantContext) -> Backend:
        self.opened.append(tenant)
        return self.backend

    async def close(self) -> None:
        await self.backend.close()

