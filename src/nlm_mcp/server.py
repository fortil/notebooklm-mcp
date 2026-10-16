"""MCP server wiring."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl

from nlm_mcp import __version__
from nlm_mcp.backends.base import BackendFactory
from nlm_mcp.backends.notebooklm_py import ProfileBackendFactory
from nlm_mcp.config import Settings
from nlm_mcp.server_state import AppState
from nlm_mcp.tenancy import UsageMeter, build_meter, rpc_recorder
from nlm_mcp.tools.artifacts import register_artifact_tools
from nlm_mcp.tools.chat import register_chat_tools
from nlm_mcp.tools.notebooks import register_notebook_tools
from nlm_mcp.tools.resources import register_resources
from nlm_mcp.tools.sharing import register_sharing_tools
from nlm_mcp.tools.sources import register_source_tools

__all__ = ["SERVER_INSTRUCTIONS", "AppState", "create_server"]

SERVER_INSTRUCTIONS = (
    "Tools to read and manage Google NotebookLM notebooks: notebooks, sources, grounded chat, "
    "generated artifacts (audio overview, report, study guide, quiz, flashcards, video, mind "
    "map, infographic, slide deck, data table), artifact downloads in every format, the "
    "account's artifact option tables and notebook public-link sharing. "
    "Notebook, source, task and artifact ids come from the list_* tools. "
    "generate_artifact is asynchronous: it returns a task_id that must be polled with get_task "
    "(mind_map with variant=note_backed completes synchronously instead). "
    "Errors start with a [CODE] prefix; AUTH_REQUIRED means the user must run "
    "`notebooklm login` for the profile."
)


def create_server(
    settings: Settings,
    *,
    factory: BackendFactory | None = None,
    meter: UsageMeter | None = None,
    token_verifier: TokenVerifier | None = None,
) -> MCPServer:
    logging.basicConfig(
        stream=sys.stderr,
        level=settings.log_level,
        format="%(levelname).1s %(name)s: %(message)s",
    )
    meter = meter if meter is not None else build_meter(settings)
    factory = (
        factory
        if factory is not None
        else ProfileBackendFactory(
            sdk_backend=settings.sdk_backend,
            max_concurrent_rpcs=settings.max_concurrent_rpcs,
            on_rpc_event=rpc_recorder(meter, "local"),
        )
    )
    state = AppState(settings=settings, factory=factory, meter=meter)

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[AppState]:
        try:
            yield state
        finally:
            await state.factory.close()

    auth = (
        AuthSettings(
            issuer_url=AnyHttpUrl("http://localhost"),
            resource_server_url=AnyHttpUrl(f"http://{settings.host}:{settings.port}"),
            required_scopes=["notebooklm"],
            validate_token_resource=False,
        )
        if token_verifier is not None
        else None
    )
    server = MCPServer(
        name="notebooklm",
        instructions=SERVER_INSTRUCTIONS,
        version=__version__,
        lifespan=lifespan,
        token_verifier=token_verifier,
        auth=auth,
    )
    register_notebook_tools(server)
    register_source_tools(server)
    register_chat_tools(server)
    register_artifact_tools(server)
    register_sharing_tools(server)
    register_resources(server, state)

    if settings.tools:
        for tool in list(server._tool_manager.list_tools()):
            if tool.name not in settings.tools:
                server.remove_tool(tool.name)
    return server
