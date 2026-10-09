"""Application state carried through the MCP lifespan."""

from dataclasses import dataclass

from nlm_mcp.backends.base import BackendFactory
from nlm_mcp.config import Settings
from nlm_mcp.tenancy import UsageMeter


@dataclass
class AppState:
    settings: Settings
    factory: BackendFactory
    meter: UsageMeter
