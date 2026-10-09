"""Chat tool."""

from mcp.server.mcpserver import Context, MCPServer

from nlm_mcp.models import ChatAnswer
from nlm_mcp.tools._common import READ_ONLY, backend_for, metered


def register_chat_tools(server: MCPServer) -> None:
    @server.tool(
        name="chat",
        description=(
            "Ask a question grounded in the notebook's sources. Pass the returned "
            "conversation_id back to continue the same conversation."
        ),
        annotations=READ_ONLY,
    )
    @metered("chat")
    async def chat(
        ctx: Context,
        notebook_id: str,
        question: str,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> ChatAnswer:
        return await (await backend_for(ctx)).ask(
            notebook_id, question, source_ids, conversation_id
        )
