"""Error contract shared by tools and backends. No SDK imports."""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError

ErrorCode = Literal[
    "AUTH_REQUIRED",
    "RATE_LIMITED",
    "QUOTA_EXCEEDED",
    "NOT_FOUND",
    "TIMEOUT",
    "UNSUPPORTED",
    "INVALID_ARGUMENT",
    "TRANSIENT",
    "UPSTREAM",
]

LOGIN_HINT = "Run `notebooklm login` (or `nlm-mcp auth login`) for this profile, then retry."


class NlmError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        hint: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message
        self.hint = hint
        self.retryable = retryable

    def to_tool_message(self) -> str:
        msg = f"[{self.code}] {self.message}"
        if self.hint:
            msg += f" Hint: {self.hint}"
        return msg


def not_found(kind: str, id: str) -> NlmError:
    return NlmError("NOT_FOUND", f"{kind} not found: {id}")


def invalid_argument(message: str) -> NlmError:
    return NlmError("INVALID_ARGUMENT", message)


def unsupported(message: str) -> NlmError:
    return NlmError("UNSUPPORTED", message)


def to_tool_error(err: NlmError) -> ToolError:
    return ToolError(err.to_tool_message())
