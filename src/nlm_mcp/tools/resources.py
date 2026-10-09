"""MCP resources."""

from mcp.server.mcpserver import Context, MCPServer

from nlm_mcp.models import NotebookList, SourceList
from nlm_mcp.server_state import AppState
from nlm_mcp.tools._common import backend_for, run_metered, tenant_for


def register_resources(server: MCPServer, state: AppState) -> None:
    # MCPServer does not inject Context into static resources, so the first one closes
    # over the app state; tenant resolution still reads the request's bearer token.
    @server.resource("notebooklm://notebooks", mime_type="application/json")
    async def notebooks_resource() -> str:
        async def call() -> str:
            backend = await state.factory.open(tenant_for(state.settings))
            return NotebookList(items=await backend.list_notebooks()).model_dump_json()

        return await run_metered(state, "resource:notebooks", call)

    @server.resource("notebooklm://notebooks/{notebook_id}/sources", mime_type="application/json")
    async def sources_resource(notebook_id: str, ctx: Context) -> str:
        async def call() -> str:
            items = await (await backend_for(ctx)).list_sources(notebook_id)
            return SourceList(items=items).model_dump_json()

        return await run_metered(state, "resource:sources", call)
