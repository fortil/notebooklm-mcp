"""Artifact tools and usage."""

import os

from mcp.server.mcpserver import Context, MCPServer

from nlm_mcp.errors import invalid_argument
from nlm_mcp.models import (
    ArtifactKind,
    ArtifactKindAny,
    ArtifactList,
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

_EXT = {"audio_overview": "m4a", "report": "md", "study_guide": "md"}


def register_artifact_tools(server: MCPServer) -> None:
    @server.tool(
        name="generate_artifact",
        description=(
            "Start generating an artifact (audio_overview, report, study_guide, quiz, "
            "flashcards). Returns immediately with a task_id; poll get_task every 15-30 s; "
            "audio can take several minutes. If get_task returns no artifact_id, use "
            "list_artifacts."
        ),
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
        description="List the generated artifacts of a notebook, optionally by kind.",
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
            "given, must be inside that directory."
        ),
        annotations=MUTATING,
    )
    @metered("download_artifact")
    async def download_artifact(
        ctx: Context, notebook_id: str, artifact_id: str, dest_dir: str | None = None
    ) -> DownloadedFile:
        settings = app_state(ctx).settings
        root = os.path.realpath(str(settings.download_dir))
        base = os.path.realpath(dest_dir) if dest_dir else root
        if not (base == root or base.startswith(root + os.sep)):
            raise invalid_argument("dest_dir must be inside NLM_MCP_DOWNLOAD_DIR")
        backend = await backend_for(ctx)
        arts = await backend.list_artifacts(notebook_id)
        kind = next((a.kind for a in arts if a.id == artifact_id), None)
        ext = _EXT.get(kind or "", "json")
        os.makedirs(base, exist_ok=True)
        dest_path = os.path.join(base, f"{artifact_id}.{ext}")
        return await backend.download_artifact(notebook_id, artifact_id, dest_path)

    @server.tool(
        name="get_usage",
        description="Show notebook/source limits, usage windows and whether the session is valid.",
        annotations=READ_ONLY,
    )
    @metered("get_usage")
    async def get_usage(ctx: Context) -> Usage:
        usage = await (await backend_for(ctx)).get_usage()
        return usage.model_copy(update={"tenant_id": current_tenant(ctx).tenant_id})
