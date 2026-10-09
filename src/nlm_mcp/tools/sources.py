"""Source tools."""

import os
from typing import Literal

from mcp.server.mcpserver import Context, MCPServer

from nlm_mcp.errors import invalid_argument, unsupported
from nlm_mcp.models import (
    AddSourceRequest,
    Deleted,
    PassageList,
    Source,
    SourceDetail,
    SourceList,
    SourceState,
)
from nlm_mcp.tools._common import (
    DESTRUCTIVE,
    MUTATING,
    READ_ONLY,
    app_state,
    backend_for,
    metered,
)


def register_source_tools(server: MCPServer) -> None:
    @server.tool(
        name="list_sources",
        description="List the sources of a notebook, optionally filtered by processing state.",
        annotations=READ_ONLY,
    )
    @metered("list_sources")
    async def list_sources(
        ctx: Context, notebook_id: str, status: SourceState | None = None
    ) -> SourceList:
        return SourceList(items=await (await backend_for(ctx)).list_sources(notebook_id, status))

    @server.tool(
        name="add_source",
        description=(
            "Add a source to a notebook. Set kind to url, text, file or drive and fill only the "
            "matching field (url, text, path, drive_document_id). wait=true blocks until the "
            "source is processed."
        ),
        annotations=MUTATING,
    )
    @metered("add_source")
    async def add_source(
        ctx: Context,
        notebook_id: str,
        kind: Literal["url", "text", "file", "drive"],
        url: str | None = None,
        text: str | None = None,
        title: str | None = None,
        path: str | None = None,
        drive_document_id: str | None = None,
        wait: bool = False,
    ) -> Source:
        req = AddSourceRequest(
            notebook_id=notebook_id,
            kind=kind,
            url=url,
            text=text,
            title=title,
            path=path,
            drive_document_id=drive_document_id,
            wait=wait,
        )
        if kind == "file":
            if not app_state(ctx).settings.allow_local_files:
                raise unsupported(
                    "local file sources are disabled on this transport; "
                    "set NLM_MCP_ALLOW_LOCAL_FILES=1"
                )
            real = os.path.realpath(path or "")
            if not os.path.isfile(real):
                raise invalid_argument(f"path is not a file: {path}")
            req = req.model_copy(update={"path": real})
        return await (await backend_for(ctx)).add_source(req)

    @server.tool(
        name="get_source",
        description="Get one source, optionally with its full text (truncated to max_chars).",
        annotations=READ_ONLY,
    )
    @metered("get_source")
    async def get_source(
        ctx: Context,
        notebook_id: str,
        source_id: str,
        fulltext: bool = False,
        max_chars: int = 20000,
    ) -> SourceDetail:
        backend = await backend_for(ctx)
        source = await backend.get_source(notebook_id, source_id)
        text: str | None = None
        truncated = False
        if fulltext:
            full = await backend.get_source_text(notebook_id, source_id)
            truncated = len(full) > max_chars
            text = full[:max_chars]
        return SourceDetail(source=source, text=text, truncated=truncated)

    @server.tool(
        name="remove_source",
        description="Permanently remove a source from a notebook.",
        annotations=DESTRUCTIVE,
    )
    @metered("remove_source")
    async def remove_source(ctx: Context, notebook_id: str, source_id: str) -> Deleted:
        await (await backend_for(ctx)).remove_source(notebook_id, source_id)
        return Deleted(id=source_id, kind="source")

    @server.tool(
        name="search_sources",
        description="Search the text of a notebook's sources and return matching passages.",
        annotations=READ_ONLY,
    )
    @metered("search_sources")
    async def search_sources(
        ctx: Context, notebook_id: str, query: str, limit: int = 10
    ) -> PassageList:
        items = await (await backend_for(ctx)).search_sources(notebook_id, query, limit)
        return PassageList(items=items)
