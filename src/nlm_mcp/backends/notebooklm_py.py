"""notebooklm-py backend. The only module in the project that imports `notebooklm`."""

from __future__ import annotations

import asyncio
import functools
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, Literal, ParamSpec, TypeVar

from notebooklm import (
    ArtifactType,
    AudioFormat,
    AudioLength,
    InfographicDetail,
    InfographicOrientation,
    InfographicStyle,
    MindMapKind,
    NotebookLMClient,
    QuizDifficulty,
    QuizQuantity,
    ReportFormat,
    ShareViewLevel,
    SlideDeckFormat,
    SlideDeckLength,
    VideoFormat,
    VideoStyle,
)
from notebooklm import exceptions as nlm_exc
from notebooklm.paths import get_storage_path

from nlm_mcp.backends.base import Backend, BackendFactory, TenantContext
from nlm_mcp.errors import LOGIN_HINT, NlmError, invalid_argument, unsupported
from nlm_mcp.models import (
    GENERATABLE_KINDS,
    AddSourceRequest,
    Artifact,
    ArtifactKindAny,
    ArtifactOptions,
    ChatAnswer,
    Citation,
    DownloadedFile,
    GenerateRequest,
    Notebook,
    OptionChoice,
    Passage,
    ReportPreset,
    SharedUser,
    ShareLevel,
    ShareStatus,
    Source,
    SourceState,
    TaskState,
    TaskStatus,
    Usage,
    UsageWindow,
)

P = ParamSpec("P")
R = TypeVar("R")


def map_sdk_exception(exc: Exception) -> NlmError:
    """Translate an SDK (or arbitrary) exception into the project error contract."""
    if isinstance(exc, NlmError):
        return exc
    if isinstance(exc, nlm_exc.NotebookLimitError):
        return NlmError("QUOTA_EXCEEDED", f"notebook limit reached: {exc}")
    if isinstance(exc, nlm_exc.RateLimitError):
        retry_after = getattr(exc, "retry_after", None)
        msg = "rate limited by NotebookLM"
        if retry_after:
            msg += f" (retry after {retry_after}s)"
        return NlmError("RATE_LIMITED", msg, retryable=True)
    if isinstance(
        exc, (nlm_exc.AuthError, nlm_exc.HeadlessReauthError, nlm_exc.AuthExtractionError)
    ):
        return NlmError("AUTH_REQUIRED", f"authentication failed: {exc}", hint=LOGIN_HINT)
    if isinstance(exc, nlm_exc.NotFoundError):
        return NlmError("NOT_FOUND", f"not found: {exc}")
    if isinstance(exc, (nlm_exc.WaitTimeoutError, nlm_exc.RPCTimeoutError)):
        return NlmError(
            "TIMEOUT",
            f"timed out: {exc}",
            hint="a timeout does not mean the operation failed; poll `get_task`/`list_sources`",
            retryable=True,
        )
    if isinstance(exc, nlm_exc.UnsupportedOperationError):
        return unsupported(str(exc))
    if isinstance(exc, nlm_exc.ConfigurationError):
        return NlmError(
            "UNSUPPORTED",
            f"configuration problem: {exc}",
            hint="check NLM_MCP_BACKEND and the installed notebooklm-py extras",
        )
    if isinstance(exc, nlm_exc.SourceProcessingError):
        return NlmError(
            "INVALID_ARGUMENT",
            f"source {exc.source_id} could not be processed by NotebookLM",
            hint="check the URL/file content and add the source again",
        )
    if isinstance(exc, (nlm_exc.ValidationError, nlm_exc.SourceAddError)):
        return invalid_argument(str(exc))
    if isinstance(exc, nlm_exc.NonIdempotentRetryError):
        return NlmError(
            "TRANSIENT",
            f"non-idempotent operation was not retried: {exc}",
            hint="the operation may have succeeded upstream; call the matching list_* tool "
            "before retrying",
            retryable=False,
        )
    if isinstance(exc, nlm_exc.NetworkError):
        return NlmError("TRANSIENT", f"network error: {exc}", retryable=True)
    if isinstance(exc, nlm_exc.NotebookLMError):
        return NlmError("UPSTREAM", f"{type(exc).__name__}: {exc}")
    return NlmError("UPSTREAM", f"{type(exc).__name__}: {exc}")


def _guard(fn: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            raise map_sdk_exception(exc) from exc

    return wrapper


_SOURCE_KINDS: dict[str, str] = {
    "youtube": "youtube",
    "web_page": "url",
    "pasted_text": "text",
    "markdown": "text",
    "google_docs": "drive",
    "google_slides": "drive",
    "google_spreadsheet": "drive",
    "google_drive": "drive",
    "google_drive_audio": "drive",
    "google_drive_video": "drive",
    "pdf": "file",
    "docx": "file",
    "csv": "file",
    "epub": "file",
    "excel": "file",
    "powerpoint": "file",
    "image": "file",
    "media": "file",
}
_SOURCE_STATES = {"preparing", "processing", "ready", "error", "unknown"}
_TASK_STATES = {"pending", "in_progress", "completed", "failed", "not_found", "unknown"}


def _enum_name(value: Any) -> str:
    return str(getattr(value, "name", value)).lower()


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value)).lower()


def _notebook(n: Any) -> Notebook:
    return Notebook(
        id=n.id,
        title=n.title or "",
        source_count=n.sources_count or 0,
        created_at=n.created_at,
        modified_at=n.modified_at,
        is_owner=bool(n.is_owner),
    )


def _source(s: Any, notebook_id: str) -> Source:
    kind: Any = _SOURCE_KINDS.get(_enum_value(s.kind), "unknown")
    state = _enum_name(s.status)
    return Source(
        id=s.id,
        notebook_id=notebook_id,
        title=s.title,
        kind=kind,
        state=state if state in _SOURCE_STATES else "unknown",  # type: ignore[arg-type]
        url=s.url,
        word_count=s.word_count,
        created_at=s.created_at,
    )


_ARTIFACT_KINDS = {
    ArtifactType.AUDIO: "audio_overview",
    ArtifactType.QUIZ: "quiz",
    ArtifactType.FLASHCARDS: "flashcards",
    ArtifactType.VIDEO: "video",
    ArtifactType.MIND_MAP: "mind_map",
    ArtifactType.INFOGRAPHIC: "infographic",
    ArtifactType.SLIDE_DECK: "slide_deck",
    ArtifactType.DATA_TABLE: "data_table",
}


def _artifact(a: Any, notebook_id: str) -> Artifact:
    kind: Any
    if a.kind == ArtifactType.REPORT:
        kind = "study_guide" if _enum_value(a.report_format) == "study_guide" else "report"
    else:
        kind = _ARTIFACT_KINDS.get(a.kind, "unknown")
    state: TaskState
    if a.is_completed:
        state = "completed"
    elif a.is_failed:
        state = "failed"
    elif a.is_pending:
        state = "pending"
    elif a.is_processing:
        state = "in_progress"
    else:
        state = "unknown"
    return Artifact(
        id=a.id,
        notebook_id=notebook_id,
        title=a.title or "",
        kind=kind,
        state=state,
        created_at=a.created_at,
        url=a.url,
    )


def _task(g: Any) -> TaskStatus:
    state = _enum_value(g.status)
    metadata = g.metadata or {}
    artifact_id = metadata.get("artifact_id")
    if not artifact_id and state == "completed":
        # The API returns a single id that is both the polling task id and the
        # artifact id once complete; metadata does not carry a separate one.
        artifact_id = g.task_id
    return TaskStatus(
        task_id=g.task_id,
        state=state if state in _TASK_STATES else "unknown",  # type: ignore[arg-type]
        artifact_id=str(artifact_id) if artifact_id else None,
        error=g.error,
    )


def _usage(tenant_id: str, summary: Any, limits: Any, notebooks_used: int) -> Usage:
    windows: list[UsageWindow] = []
    for w in summary.windows:
        name = _enum_name(w.kind)
        wkind: Any = name if name in ("five_hour", "weekly") else "unknown"
        windows.append(
            UsageWindow(
                kind=wkind,
                used_percent=float(w.used_percent),
                remaining_percent=float(w.remaining_percent),
                resets_at=w.resets_at,
            )
        )
    return Usage(
        tenant_id=tenant_id,
        notebooks_used=notebooks_used,
        notebook_limit=limits.notebook_limit,
        source_limit=limits.source_limit,
        windows=windows,
        session_ok=True,
    )


_DOWNLOAD_FORMATS: dict[str, frozenset[str]] = {
    "slide_deck": frozenset({"pdf", "pptx"}),
    "quiz": frozenset({"json", "markdown", "html"}),
    "flashcards": frozenset({"json", "markdown", "html"}),
}
_DEFAULT_DOWNLOAD_FORMAT = {"quiz": "json", "flashcards": "json", "slide_deck": "pdf"}

_SHARE_PERMISSIONS = {"owner", "editor", "viewer"}


def _share_status(s: Any, notebook_id: str) -> ShareStatus:
    access = _enum_name(s.access)
    view_level = _enum_name(s.view_level)
    users: list[SharedUser] = []
    for u in s.shared_users or []:
        permission = _enum_name(u.permission)
        users.append(
            SharedUser(
                email=u.email,
                permission=permission if permission in _SHARE_PERMISSIONS else "unknown",  # type: ignore[arg-type]
                display_name=u.display_name,
            )
        )
    return ShareStatus(
        notebook_id=notebook_id,
        is_public=bool(s.is_public),
        access=access if access in ("restricted", "anyone_with_link") else "restricted",  # type: ignore[arg-type]
        view_level=view_level if view_level in ("full_notebook", "chat_only") else "full_notebook",  # type: ignore[arg-type]
        share_url=s.share_url,
        shared_users=users,
        is_public_sharing_allowed=s.is_public_sharing_allowed,
    )


def _enum_option(enum_cls: Any, options: dict[str, str], key: str) -> Any:
    raw = options.get(key)
    if raw is None:
        return None
    try:
        return enum_cls[raw.upper()]
    except KeyError:
        raise invalid_argument(f"invalid value {raw!r} for option {key!r}") from None


def _check_options(options: dict[str, str], allowed: set[str]) -> None:
    unknown = set(options) - allowed
    if unknown:
        raise invalid_argument(f"unknown option(s) for this kind: {sorted(unknown)}")


class NotebookLmPyBackend(Backend):
    def __init__(self, client: NotebookLMClient, *, tenant_id: str) -> None:
        self._c = client
        self._tenant_id = tenant_id

    @_guard
    async def list_notebooks(self) -> list[Notebook]:
        return [_notebook(n) for n in await self._c.notebooks.list()]

    @_guard
    async def get_notebook(self, notebook_id: str) -> Notebook:
        return _notebook(await self._c.notebooks.get(notebook_id))

    @_guard
    async def get_notebook_summary(self, notebook_id: str) -> str | None:
        summary = await self._c.notebooks.get_summary(notebook_id)
        return str(summary) if summary else None

    @_guard
    async def create_notebook(self, title: str) -> Notebook:
        return _notebook(await self._c.notebooks.create(title))

    @_guard
    async def rename_notebook(self, notebook_id: str, title: str) -> Notebook:
        return _notebook(await self._c.notebooks.rename(notebook_id, title))

    @_guard
    async def delete_notebook(self, notebook_id: str) -> None:
        await self._c.notebooks.delete(notebook_id)

    @_guard
    async def list_sources(
        self, notebook_id: str, state: SourceState | None = None
    ) -> list[Source]:
        items = [_source(s, notebook_id) for s in await self._c.sources.list(notebook_id)]
        if state is not None:
            items = [s for s in items if s.state == state]
        return items

    @_guard
    async def get_source(self, notebook_id: str, source_id: str) -> Source:
        return _source(await self._c.sources.get(notebook_id, source_id), notebook_id)

    @_guard
    async def get_source_text(self, notebook_id: str, source_id: str) -> str:
        res = await self._c.sources.get_fulltext(notebook_id, source_id, output_format="text")
        return str(res.content)

    @_guard
    async def add_source(self, req: AddSourceRequest) -> Source:
        nb = req.notebook_id
        s = self._c.sources
        if req.kind == "url":
            assert req.url is not None
            src = await s.add_url(nb, req.url, title=req.title, wait=req.wait, wait_timeout=120)
        elif req.kind == "text":
            assert req.text is not None
            # No idempotent=True: the SDK rejects it for text sources (no
            # reliable server-side dedupe key), so retried adds can duplicate.
            src = await s.add_text(nb, req.title or "Pasted text", req.text, wait=req.wait)
        elif req.kind == "file":
            assert req.path is not None
            src = await s.add_file(nb, req.path, title=req.title, wait=req.wait)
        else:
            assert req.drive_document_id is not None
            src = await s.add_drive_file(
                nb, req.drive_document_id, title=req.title, wait=req.wait
            )
        return _source(src, nb)

    @_guard
    async def remove_source(self, notebook_id: str, source_id: str) -> None:
        await self._c.sources.delete(notebook_id, source_id)

    @_guard
    async def search_sources(self, notebook_id: str, query: str, limit: int) -> list[Passage]:
        chunks = await self._c.sources.search(notebook_id, query, limit=limit)
        return [Passage(source_id=c.source_id, text=c.text, rank=c.rank) for c in chunks]

    @_guard
    async def ask(
        self,
        notebook_id: str,
        question: str,
        source_ids: list[str] | None,
        conversation_id: str | None,
    ) -> ChatAnswer:
        r = await self._c.chat.ask(notebook_id, question, source_ids, conversation_id)
        return ChatAnswer(
            answer=r.answer,
            conversation_id=r.conversation_id,
            turn_number=r.turn_number,
            citations=[
                Citation(source_id=ref.source_id, number=ref.citation_number, text=ref.cited_text)
                for ref in (r.references or [])
            ],
        )

    @_guard
    async def generate_artifact(self, req: GenerateRequest) -> TaskStatus:
        nb, a, opt = req.notebook_id, self._c.artifacts, req.options
        if req.kind == "audio_overview":
            _check_options(opt, {"format", "length"})
            g = await a.generate_audio(
                nb,
                req.source_ids,
                req.language,
                req.instructions,
                audio_format=_enum_option(AudioFormat, opt, "format"),
                audio_length=_enum_option(AudioLength, opt, "length"),
            )
        elif req.kind == "video":
            _check_options(opt, {"format", "style", "style_prompt"})
            video_format = _enum_option(VideoFormat, opt, "format")
            if video_format is VideoFormat.CINEMATIC:
                _check_options(opt, set())
                g = await a.generate_cinematic_video(
                    nb, req.source_ids, req.language, req.instructions
                )
            else:
                g = await a.generate_video(
                    nb,
                    req.source_ids,
                    req.language,
                    req.instructions,
                    video_format=video_format,
                    video_style=_enum_option(VideoStyle, opt, "style"),
                    style_prompt=opt.get("style_prompt"),
                )
        elif req.kind == "report":
            _check_options(opt, {"format", "custom_prompt"})
            report_format = _enum_option(ReportFormat, opt, "format") or ReportFormat.BRIEFING_DOC
            if report_format == ReportFormat.STUDY_GUIDE:
                raise invalid_argument("use kind='study_guide' instead of format='study_guide'")
            custom_prompt = opt.get("custom_prompt")
            if custom_prompt is not None and report_format != ReportFormat.CUSTOM:
                raise invalid_argument(
                    "option 'custom_prompt' is only valid with format='custom'"
                )
            g = await a.generate_report(
                nb,
                report_format=report_format,
                source_ids=req.source_ids,
                language=req.language,
                custom_prompt=custom_prompt,
                extra_instructions=req.instructions,
            )
        elif req.kind == "study_guide":
            _check_options(opt, set())
            g = await a.generate_study_guide(
                nb, req.source_ids, req.language, extra_instructions=req.instructions
            )
        elif req.kind == "quiz" or req.kind == "flashcards":
            _check_options(opt, {"quantity", "difficulty"})
            fn = a.generate_quiz if req.kind == "quiz" else a.generate_flashcards
            g = await fn(
                nb,
                req.source_ids,
                req.instructions,
                quantity=_enum_option(QuizQuantity, opt, "quantity"),
                difficulty=_enum_option(QuizDifficulty, opt, "difficulty"),
            )
        elif req.kind == "mind_map":
            return await self._generate_mind_map(req)
        elif req.kind == "infographic":
            _check_options(opt, {"orientation", "detail", "style"})
            g = await a.generate_infographic(
                nb,
                req.source_ids,
                req.language,
                req.instructions,
                orientation=_enum_option(InfographicOrientation, opt, "orientation"),
                detail_level=_enum_option(InfographicDetail, opt, "detail"),
                style=_enum_option(InfographicStyle, opt, "style"),
            )
        elif req.kind == "slide_deck":
            _check_options(opt, {"format", "length"})
            g = await a.generate_slide_deck(
                nb,
                req.source_ids,
                req.language,
                req.instructions,
                slide_format=_enum_option(SlideDeckFormat, opt, "format"),
                slide_length=_enum_option(SlideDeckLength, opt, "length"),
            )
        elif req.kind == "data_table":
            _check_options(opt, set())
            g = await a.generate_data_table(nb, req.source_ids, req.language, req.instructions)
        else:
            # Unreachable while GenerateRequest.kind stays a Literal over
            # GENERATABLE_KINDS; kept so an unknown kind can never silently
            # fall through to another generator.
            raise invalid_argument(
                f"unsupported artifact kind {req.kind!r}; "
                f"supported kinds: {', '.join(GENERATABLE_KINDS)}"
            )
        return _task(g)

    async def _generate_mind_map(self, req: GenerateRequest) -> TaskStatus:
        """Generate a mind map. Note-backed is synchronous, interactive is a task.

        The note-backed variant (GENERATE_MIND_MAP) returns the finished tree
        in one call, so the honest task state is already `completed` with the
        note id as both task and artifact id. The interactive variant is a
        regular CREATE_ARTIFACT task: return pending and let get_task poll.
        """
        _check_options(req.options, {"variant"})
        variant = req.options.get("variant", "note_backed")
        if variant == "interactive":
            mm = await self._c.mind_maps.generate(
                req.notebook_id,
                req.source_ids,
                kind=MindMapKind.INTERACTIVE,
                language=req.language,
                instructions=req.instructions,
                wait=False,
            )
            return TaskStatus(
                task_id=mm.id, state="pending", artifact_id=None, error=None
            )
        if variant != "note_backed":
            raise invalid_argument(
                f"invalid value {variant!r} for option 'variant' (note_backed or interactive)"
            )
        res = await self._c.artifacts.generate_mind_map(
            req.notebook_id, req.source_ids, req.language, req.instructions
        )
        if not res.note_id:
            raise NlmError("UPSTREAM", "mind map generated but the SDK returned no note id")
        return TaskStatus(
            task_id=res.note_id, state="completed", artifact_id=res.note_id, error=None
        )

    @_guard
    async def get_task(self, notebook_id: str, task_id: str) -> TaskStatus:
        return _task(await self._c.artifacts.poll_status(notebook_id, task_id))

    @_guard
    async def list_artifacts(
        self, notebook_id: str, kind: ArtifactKindAny | None = None
    ) -> list[Artifact]:
        items = [_artifact(a, notebook_id) for a in await self._c.artifacts.list(notebook_id)]
        if kind is not None:
            items = [a for a in items if a.kind == kind]
        return items

    @_guard
    async def download_artifact(
        self,
        notebook_id: str,
        artifact_id: str,
        dest_path: str,
        output_format: str | None = None,
    ) -> DownloadedFile:
        a = self._c.artifacts
        art = await a.get(notebook_id, artifact_id)
        wire_kind = _enum_value(art.kind)
        fmt = output_format or _DEFAULT_DOWNLOAD_FORMAT.get(wire_kind)
        allowed = _DOWNLOAD_FORMATS.get(wire_kind)
        if allowed is not None:
            if fmt is None or fmt not in allowed:
                raise invalid_argument(
                    f"invalid output_format {fmt!r} for {wire_kind}; "
                    f"use one of: {', '.join(sorted(allowed))}"
                )
        elif output_format is not None:
            raise invalid_argument(f"{wire_kind} artifacts take no output_format")
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        if art.kind == ArtifactType.AUDIO:
            path = await a.download_audio(notebook_id, dest_path, artifact_id=artifact_id)
        elif art.kind == ArtifactType.VIDEO:
            path = await a.download_video(notebook_id, dest_path, artifact_id=artifact_id)
        elif art.kind == ArtifactType.REPORT:
            path = await a.download_report(notebook_id, dest_path, artifact_id=artifact_id)
        elif art.kind == ArtifactType.QUIZ:
            path = await a.download_quiz(
                notebook_id, dest_path, artifact_id=artifact_id, output_format=fmt or "json"
            )
        elif art.kind == ArtifactType.FLASHCARDS:
            path = await a.download_flashcards(
                notebook_id, dest_path, artifact_id=artifact_id, output_format=fmt or "json"
            )
        elif art.kind == ArtifactType.MIND_MAP:
            path = await a.download_mind_map(notebook_id, dest_path, artifact_id=artifact_id)
        elif art.kind == ArtifactType.INFOGRAPHIC:
            path = await a.download_infographic(notebook_id, dest_path, artifact_id=artifact_id)
        elif art.kind == ArtifactType.SLIDE_DECK:
            path = await a.download_slide_deck(
                notebook_id, dest_path, artifact_id=artifact_id, output_format=fmt or "pdf"
            )
        elif art.kind == ArtifactType.DATA_TABLE:
            path = await a.download_data_table(notebook_id, dest_path, artifact_id=artifact_id)
        else:
            raise unsupported(f"download of {wire_kind} not supported")
        out = str(path)
        return DownloadedFile(artifact_id=artifact_id, path=out, bytes=os.path.getsize(out))

    @_guard
    async def get_artifact_options(self, notebook_id: str | None = None) -> ArtifactOptions:
        choices = await self._c.artifacts.get_customization_choices(notebook_id)

        def option(choice: Any, enum_cls: Any) -> OptionChoice:
            try:
                value = _enum_name(enum_cls(choice.code))
            except ValueError:
                value = "unknown"
            return OptionChoice(
                code=choice.code,
                value=value,
                title=choice.title,
                description=choice.description,
            )

        return ArtifactOptions(
            audio=[option(c, AudioFormat) for c in choices.audio],
            video=[option(c, VideoFormat) for c in choices.video],
            slide_deck=[option(c, SlideDeckFormat) for c in choices.slide_deck],
            reports=[
                ReportPreset(
                    title=p.report_type, description=p.description, directive=p.directive
                )
                for p in choices.reports
            ],
        )

    @_guard
    async def get_share_status(self, notebook_id: str) -> ShareStatus:
        return _share_status(await self._c.sharing.get_status(notebook_id), notebook_id)

    @_guard
    async def set_notebook_public(
        self, notebook_id: str, public: bool, view_level: ShareLevel | None
    ) -> ShareStatus:
        status = await self._c.sharing.set_public(notebook_id, public)
        if view_level is not None:
            status = await self._c.sharing.set_view_level(
                notebook_id, ShareViewLevel[view_level.upper()]
            )
        return _share_status(status, notebook_id)

    @_guard
    async def get_usage(self) -> Usage:
        summary = await self._c.settings.get_usage()
        limits = await self._c.settings.get_account_limits()
        used = len(await self._c.notebooks.list())
        return _usage(self._tenant_id, summary, limits, used)

    async def close(self) -> None:
        return None


class ProfileBackendFactory(BackendFactory):
    def __init__(
        self,
        *,
        sdk_backend: Literal["web", "android"],
        max_concurrent_rpcs: int,
        on_rpc_event: Callable[[str, str, float], None] | None,
    ) -> None:
        self._sdk_backend = sdk_backend
        self._max_rpcs = max_concurrent_rpcs
        self._on_rpc_event = on_rpc_event
        self._contexts: dict[str, Any] = {}
        self._backends: dict[str, NotebookLmPyBackend] = {}
        self._lock = asyncio.Lock()

    def _adapter(self) -> Callable[[Any], object] | None:
        cb = self._on_rpc_event
        if cb is None:
            return None

        def adapter(event: Any) -> object:
            cb(str(event.method), str(event.status), float(event.elapsed_seconds))
            return None

        return adapter

    async def open(self, tenant: TenantContext) -> Backend:
        async with self._lock:
            return await self._open_locked(tenant)

    async def _open_locked(self, tenant: TenantContext) -> Backend:
        cached = self._backends.get(tenant.tenant_id)
        if cached is not None:
            return cached
        try:
            ctx = NotebookLMClient.from_storage(
                profile=tenant.profile,
                backend=self._sdk_backend,
                max_concurrent_rpcs=self._max_rpcs,
                on_rpc_event=self._adapter(),
            )
            client = await ctx.__aenter__()
        except (FileNotFoundError, nlm_exc.ConfigurationError) as exc:
            raise NlmError(
                "AUTH_REQUIRED",
                f"no stored session for profile {tenant.profile!r}",
                hint=LOGIN_HINT,
            ) from exc
        except Exception as exc:
            raise map_sdk_exception(exc) from exc
        backend = NotebookLmPyBackend(client, tenant_id=tenant.tenant_id)
        self._contexts[tenant.tenant_id] = ctx
        self._backends[tenant.tenant_id] = backend
        return backend

    async def close(self) -> None:
        contexts, self._contexts = self._contexts, {}
        self._backends = {}
        for ctx in contexts.values():
            await ctx.__aexit__(None, None, None)


def storage_path_for(profile: str) -> Path:
    return Path(get_storage_path(profile))
