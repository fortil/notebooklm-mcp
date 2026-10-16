"""Notebook sharing tools (public link)."""

from mcp.server.mcpserver import Context, MCPServer

from nlm_mcp.models import ShareLevel, ShareStatus
from nlm_mcp.tools._common import IDEMPOTENT, READ_ONLY, backend_for, metered


def register_sharing_tools(server: MCPServer) -> None:
    @server.tool(
        name="get_share_status",
        description=(
            "Show how a notebook is shared: public link on/off, what viewers can access "
            "(full_notebook or chat_only), share URL and the list of shared users."
        ),
        annotations=READ_ONLY,
    )
    @metered("get_share_status")
    async def get_share_status(ctx: Context, notebook_id: str) -> ShareStatus:
        return await (await backend_for(ctx)).get_share_status(notebook_id)

    @server.tool(
        name="share_notebook",
        description=(
            "Turn the notebook's public link on or off. With public=true, optionally set "
            "view_level (full_notebook = chat + sources + notes, chat_only = chat interface "
            "only); when the link is on, the response carries the share URL. public=false "
            "removes the link; only explicitly shared users keep access."
        ),
        annotations=IDEMPOTENT,
    )
    @metered("share_notebook")
    async def share_notebook(
        ctx: Context,
        notebook_id: str,
        public: bool,
        view_level: ShareLevel | None = None,
    ) -> ShareStatus:
        return await (await backend_for(ctx)).set_notebook_public(notebook_id, public, view_level)
