"""Runtime settings read once from NLM_MCP_* environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


def _bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    profile: str = "default"
    sdk_backend: Literal["web", "android"] = "web"
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8765
    tools: frozenset[str] = frozenset()
    download_dir: Path = Path("~/.nlm-mcp/downloads").expanduser()
    allow_local_files: bool = True
    max_concurrent_rpcs: int = 4
    usage_log: Path | None = None
    tokens_file: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e: Mapping[str, str] = os.environ if env is None else env

        profile = e.get("NLM_MCP_PROFILE") or e.get("NOTEBOOKLM_PROFILE") or "default"

        sdk_backend = e.get("NLM_MCP_BACKEND") or e.get("NOTEBOOKLM_BACKEND") or "web"
        if sdk_backend not in ("web", "android"):
            raise ValueError(f"NLM_MCP_BACKEND must be 'web' or 'android', got {sdk_backend!r}")

        transport = e.get("NLM_MCP_TRANSPORT") or "stdio"
        if transport not in ("stdio", "streamable-http"):
            raise ValueError(
                f"NLM_MCP_TRANSPORT must be 'stdio' or 'streamable-http', got {transport!r}"
            )

        raw_port = e.get("NLM_MCP_PORT") or "8765"
        try:
            port = int(raw_port)
        except ValueError:
            raise ValueError(f"NLM_MCP_PORT must be an integer, got {raw_port!r}") from None

        raw_rpcs = e.get("NLM_MCP_MAX_CONCURRENT_RPCS") or "4"
        try:
            max_rpcs = int(raw_rpcs)
        except ValueError:
            raise ValueError(
                f"NLM_MCP_MAX_CONCURRENT_RPCS must be an integer, got {raw_rpcs!r}"
            ) from None

        tools = frozenset(t.strip() for t in (e.get("NLM_MCP_TOOLS") or "").split(",") if t.strip())

        raw_files = e.get("NLM_MCP_ALLOW_LOCAL_FILES")
        allow_files = _bool(raw_files) if raw_files else transport == "stdio"

        download_dir = Path(e.get("NLM_MCP_DOWNLOAD_DIR") or "~/.nlm-mcp/downloads").expanduser()
        usage_log = e.get("NLM_MCP_USAGE_LOG")
        tokens_file = e.get("NLM_MCP_TOKENS_FILE")

        return cls(
            profile=profile,
            sdk_backend=cast(Literal["web", "android"], sdk_backend),
            transport=cast(Literal["stdio", "streamable-http"], transport),
            host=e.get("NLM_MCP_HOST") or "127.0.0.1",
            port=port,
            tools=tools,
            download_dir=download_dir,
            allow_local_files=allow_files,
            max_concurrent_rpcs=max_rpcs,
            usage_log=Path(usage_log).expanduser() if usage_log else None,
            tokens_file=Path(tokens_file).expanduser() if tokens_file else None,
        )

    def validate_for_serve(self) -> None:
        if self.transport == "streamable-http" and self.tokens_file is None:
            raise ValueError(
                "NLM_MCP_TOKENS_FILE is required when NLM_MCP_TRANSPORT=streamable-http"
            )
