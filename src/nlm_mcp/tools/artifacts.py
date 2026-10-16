"""Artifact tools and usage."""

import os

from mcp.server.mcpserver import Context, MCPServer

from nlm_mcp.errors import invalid_argument, not_found
from nlm_mcp.models import (
    GENERATABLE_KINDS,
    ArtifactKind,
    ArtifactKindAny,
    ArtifactList,
    ArtifactOptions,
    DownloadedFile,
    GenerateRequest,
    TaskStatus,
    Usage,
)
from nlm_mcp.tools._common import (
    MUTATING,
    READ_ONLY,
    app_state,
    backend_for,
    current_tenant,
    metered,
)

_EXT = {
    "audio_overview": "m4a",
    "report": "md",
    "study_guide": "md",
    "quiz": "json",
    "flashcards": "json",
    "video": "mp4",
    "mind_map": "json",
    "infographic": "png",
    "slide_deck": "pdf",
    "data_table": "csv",
}
_FORMAT_EXT = {"markdown": "md"}
_DOWNLOAD_FORMATS = {
    "slide_deck": {"pdf", "pptx"},
    "quiz": {"json", "markdown", "html"},
    "flashcards": {"json", "markdown", "html"},
}

_KINDS_LIST = ", ".join(GENERATABLE_KINDS)

_GENERATE_DESCRIPTION = (
    f"Start generating an artifact. kind is one of: {_KINDS_LIST}. Returns a task_id; "
    "poll get_task every 15-30 s (audio and video can take several minutes). kind decides "
    "which options are accepted (unknown options are rejected): "
    "audio_overview: format=deep_dive|brief|critique|debate, length=short|default|long; "
    "video: format=explainer|brief|cinematic|short, style=auto_select|custom|classic|whiteboard|"
    "kawaii|anime|watercolor|retro_print|heritage|paper_craft, style_prompt (requires "
    "style=custom; never with cinematic or short); "
    "report: format=briefing_doc|blog_post|concept_explanation|custom, custom_prompt (custom "
    "only); quiz and flashcards: quantity=fewer|standard|more, difficulty=easy|medium|hard; "
    "mind_map: variant=note_backed|interactive (note_backed completes synchronously and "
    "returns state=completed with artifact_id immediately; interactive is a pollable task); "
    "infographic: orientation=landscape|portrait|square, detail=concise|standard|detailed, "
    "style=auto_select|sketch_note|professional|bento_grid|editorial|instructional|bricks|clay|"
    "anime|kawaii|scientific; slide_deck: format=detailed_deck|presenter_slides, "
    "length=default|short; study_guide and data_table take no options. "
    "language is an en-style code (en, es, ...); instructions is free text (for slide decks "
    "the UI's audience field is expressed here). If get_task returns no artifact_id, use "
    "list_artifacts."
)


def register_artifact_tools(server: MCPServer) -> None:
    @server.tool(
        name="generate_artifact",
        description=_GENERATE_DESCRIPTION,
        annotations=MUTATING,
    )
    @metered("generate_artifact")
    async def generate_artifact(
        ctx: Context,
        notebook_id: str,
        kind: ArtifactKind,
        source_ids: list[str] | None = None,
        instructions: str | None = None,
        language: str = "en",
        options: dict[str, str] | None = None,
    ) -> TaskStatus:
        if kind not in GENERATABLE_KINDS:
            raise invalid_argument(
                f"unsupported artifact kind {kind!r}; supported kinds: {_KINDS_LIST}"
            )
        req = GenerateRequest(
            notebook_id=notebook_id,
            kind=kind,
            source_ids=source_ids,
            instructions=instructions,
            language=language,
            options=options or {},
        )
        return await (await backend_for(ctx)).generate_artifact(req)

    @server.tool(
        name="get_task",
        description="Get the state of an artifact generation task started by generate_artifact.",
        annotations=READ_ONLY,
    )
    @metered("get_task")
    async def get_task(ctx: Context, notebook_id: str, task_id: str) -> TaskStatus:
        return await (await backend_for(ctx)).get_task(notebook_id, task_id)

    @server.tool(
        name="list_artifacts",
        description=(
            "List the generated artifacts of a notebook, optionally by kind "
            f"({_KINDS_LIST})."
        ),
        annotations=READ_ONLY,
    )
    @metered("list_artifacts")
    async def list_artifacts(
        ctx: Context, notebook_id: str, kind: ArtifactKindAny | None = None
    ) -> ArtifactList:
        return ArtifactList(items=await (await backend_for(ctx)).list_artifacts(notebook_id, kind))

    @server.tool(
        name="download_artifact",
        description=(
            "Download a completed artifact to the server's download directory. dest_dir, if "
            "given, must be inside that directory. format selects the file type for kinds "
            "that have more than one: slide_deck pdf|pptx, quiz and flashcards "
            "json|markdown|html."
        ),
        annotations=MUTATING,
    )
    @metered("download_artifact")
    async def download_artifact(
        ctx: Context,
        notebook_id: str,
        artifact_id: str,
        dest_dir: str | None = None,
        format: str | None = None,
    ) -> DownloadedFile:
        settings = app_state(ctx).settings
        root = os.path.realpath(str(settings.download_dir))
        base = os.path.realpath(dest_dir) if dest_dir else root
        if not (base == root or base.startswith(root + os.sep)):
            raise invalid_argument("dest_dir must be inside NLM_MCP_DOWNLOAD_DIR")
        backend = await backend_for(ctx)
        arts = await backend.list_artifacts(notebook_id)
        kind = next((a.kind for a in arts if a.id == artifact_id), None)
        if kind is None:
            raise not_found("artifact", artifact_id)
        if format is not None:
            allowed = _DOWNLOAD_FORMATS.get(kind)
            if allowed is None:
                raise invalid_argument(f"{kind} artifacts take no format")
            if format not in allowed:
                valid = ", ".join(sorted(allowed))
                raise invalid_argument(f"invalid format {format!r} for {kind}; use one of: {valid}")
        ext = _EXT.get(kind, "json")
        if format == "markdown":
            ext = "md"
        elif format in ("pdf", "pptx", "html"):
            ext = format
        os.makedirs(base, exist_ok=True)
        dest_path = os.path.join(base, f"{artifact_id}.{ext}")
        return await backend.download_artifact(notebook_id, artifact_id, dest_path, format)

    @server.tool(
        name="get_artifact_options",
        description=(
            "Show the artifact option tables this NotebookLM account offers (audio, video and "
            "slide deck formats, report presets), with the option values generate_artifact "
            "expects. Read-only and account-level; notebook_id is optional."
        ),
        annotations=READ_ONLY,
    )
    @metered("get_artifact_options")
    async def get_artifact_options(
        ctx: Context, notebook_id: str | None = None
    ) -> ArtifactOptions:
        return await (await backend_for(ctx)).get_artifact_options(notebook_id)

    @server.tool(
        name="get_usage",
        description="Show notebook/source limits, usage windows and whether the session is valid.",
        annotations=READ_ONLY,
    )
    @metered("get_usage")
    async def get_usage(ctx: Context) -> Usage:
        usage = await (await backend_for(ctx)).get_usage()
        return usage.model_copy(update={"tenant_id": current_tenant(ctx).tenant_id})
