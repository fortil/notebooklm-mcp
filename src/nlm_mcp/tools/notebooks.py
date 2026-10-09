"""Notebook tools."""

from mcp.server.mcpserver import Context, MCPServer

from nlm_mcp.models import Deleted, Notebook, NotebookDetail, NotebookList
from nlm_mcp.tools._common import (
    DESTRUCTIVE,
    IDEMPOTENT,
    MUTATING,
    READ_ONLY,
    backend_for,
    metered,
)


def register_notebook_tools(server: MCPServer) -> None:
    @server.tool(
        name="list_notebooks",
        description="List notebooks, optionally filtered by a case-insensitive title substring.",
        annotations=READ_ONLY,
    )
    @metered("list_notebooks")
    async def list_notebooks(
        ctx: Context, query: str | None = None, limit: int = 50
    ) -> NotebookList:
        items = await (await backend_for(ctx)).list_notebooks()
        if query:
            q = query.lower()
            items = [n for n in items if q in n.title.lower()]
        return NotebookList(items=items[: max(limit, 0)])

    @server.tool(
        name="get_notebook",
        description="Get one notebook, optionally with its generated summary.",
        annotations=READ_ONLY,
    )
    @metered("get_notebook")
    async def get_notebook(
        ctx: Context, notebook_id: str, include_summary: bool = False
    ) -> NotebookDetail:
        backend = await backend_for(ctx)
        nb = await backend.get_notebook(notebook_id)
        summary = await backend.get_notebook_summary(notebook_id) if include_summary else None
        return NotebookDetail(notebook=nb, summary=summary)

    @server.tool(
        name="create_notebook",
        description=(
            "Create a notebook. Not idempotent upstream: on error, call "
            "list_notebooks(query=title) before retrying."
        ),
        annotations=MUTATING,
    )
    @metered("create_notebook")
    async def create_notebook(ctx: Context, title: str) -> Notebook:
        return await (await backend_for(ctx)).create_notebook(title)

    @server.tool(
        name="rename_notebook",
        description="Rename a notebook.",
        annotations=IDEMPOTENT,
    )
    @metered("rename_notebook")
    async def rename_notebook(
        ctx: Context, notebook_id: str, title: str
    ) -> Notebook:
        return await (await backend_for(ctx)).rename_notebook(notebook_id, title)

    @server.tool(
        name="delete_notebook",
        description="Permanently delete a notebook and its sources.",
        annotations=DESTRUCTIVE,
    )
    @metered("delete_notebook")
    async def delete_notebook(
        ctx: Context, notebook_id: str
    ) -> Deleted:
        await (await backend_for(ctx)).delete_notebook(notebook_id)
        return Deleted(id=notebook_id, kind="notebook")
