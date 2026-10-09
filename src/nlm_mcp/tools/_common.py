"""Shared helpers for tool modules: annotations, tenant resolution, metering."""

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

import pydantic
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from nlm_mcp.backends.base import Backend, TenantContext
from nlm_mcp.config import Settings
from nlm_mcp.errors import NlmError, to_tool_error
from nlm_mcp.server_state import AppState
from nlm_mcp.tenancy import UsageEvent, now_iso

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)
MUTATING = ToolAnnotations(read_only_hint=False, destructive_hint=False)
IDEMPOTENT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)

R = TypeVar("R")


def app_state(ctx: Context) -> AppState:
    return cast(AppState, ctx.request_context.lifespan_context)


def tenant_for(settings: Settings) -> TenantContext:
    token = get_access_token()
    if token is not None:
        return TenantContext(
            tenant_id=token.subject or token.client_id,
            profile=str((token.claims or {})["profile"]),
            sdk_backend=settings.sdk_backend,
        )
    return TenantContext("local", settings.profile, settings.sdk_backend)


def current_tenant(ctx: Context) -> TenantContext:
    return tenant_for(app_state(ctx).settings)


async def backend_for(ctx: Context) -> Backend:
    return await app_state(ctx).factory.open(current_tenant(ctx))


async def run_metered(state: AppState, tool_name: str, call: Callable[[], Awaitable[R]]) -> R:
    """Run `call`, record a UsageEvent and convert every failure to a coded ToolError."""
    start = time.perf_counter()
    error_code: str | None = None
    err: ToolError | None = None
    result: R | None = None
    try:
        result = await call()
    except NlmError as e:
        error_code = e.code
        err = to_tool_error(e)
    except ToolError as e:
        error_code = "UPSTREAM"
        err = e
    except pydantic.ValidationError as e:
        error_code = "INVALID_ARGUMENT"
        err = ToolError(f"[INVALID_ARGUMENT] {e}")
    except Exception as e:
        error_code = "UPSTREAM"
        err = ToolError(f"[UPSTREAM] {type(e).__name__}: {e}")
    state.meter.record(
        UsageEvent(
            ts=now_iso(),
            tenant_id=tenant_for(state.settings).tenant_id,
            tool=tool_name,
            ok=err is None,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            error_code=error_code,
        )
    )
    if err is not None:
        raise err
    return result  # type: ignore[return-value]


def metered(
    tool_name: str,
) -> Callable[[Callable[..., Awaitable[R]]], Callable[..., Awaitable[R]]]:
    def decorator(fn: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> R:
            ctx: Context = kwargs.get("ctx") or next(a for a in args if isinstance(a, Context))
            return await run_metered(
                app_state(ctx), tool_name, lambda: fn(*args, **kwargs)
            )

        return wrapper

    return decorator
