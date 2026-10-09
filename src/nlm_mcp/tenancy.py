"""Tenant context and usage metering (the billing seam)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from nlm_mcp.backends.base import TenantContext
from nlm_mcp.config import Settings

__all__ = [
    "JsonlUsageMeter",
    "NullUsageMeter",
    "TenantContext",
    "UsageEvent",
    "UsageMeter",
    "build_meter",
    "now_iso",
    "rpc_recorder",
]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class UsageEvent:
    ts: str
    tenant_id: str
    tool: str
    ok: bool
    elapsed_ms: int
    error_code: str | None = None


class UsageMeter(Protocol):
    def record(self, event: UsageEvent) -> None: ...


class NullUsageMeter:
    def record(self, event: UsageEvent) -> None:
        return None


class JsonlUsageMeter:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def record(self, event: UsageEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(event)) + "\n")


def rpc_recorder(meter: UsageMeter, tenant_id: str) -> Callable[[str, str, float], None]:
    def record(method: str, status: str, elapsed_seconds: float) -> None:
        meter.record(
            UsageEvent(
                ts=now_iso(),
                tenant_id=tenant_id,
                tool=f"rpc:{method}",
                ok=status == "success",
                elapsed_ms=int(elapsed_seconds * 1000),
                error_code=None if status == "success" else status,
            )
        )

    return record


def build_meter(settings: Settings) -> UsageMeter:
    if settings.usage_log is None:
        return NullUsageMeter()
    return JsonlUsageMeter(settings.usage_log)
