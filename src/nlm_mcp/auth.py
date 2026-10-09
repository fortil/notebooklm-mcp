"""Static bearer-token verifier mapping tokens to tenants (streamable-http)."""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from mcp.server.auth.provider import AccessToken, TokenVerifier


class TenantRecord(TypedDict):
    tenant_id: str
    profile: str


class StaticTokenVerifier(TokenVerifier):
    def __init__(self, tokens: Mapping[str, TenantRecord]) -> None:
        self._tokens = dict(tokens)

    @classmethod
    def from_file(cls, path: Path) -> StaticTokenVerifier:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"tokens file {path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"tokens file {path} must be a JSON object")
        tokens: dict[str, TenantRecord] = {}
        for token, rec in raw.items():
            if (
                not isinstance(token, str)
                or not token
                or not isinstance(rec, dict)
                or not isinstance(rec.get("tenant_id"), str)
                or not isinstance(rec.get("profile"), str)
                or not rec["tenant_id"]
                or not rec["profile"]
            ):
                raise ValueError(
                    "tokens file entries must look like "
                    '"<token>": {"tenant_id": "...", "profile": "..."}'
                )
            tokens[token] = {"tenant_id": rec["tenant_id"], "profile": rec["profile"]}
        return cls(tokens)

    async def verify_token(self, token: str) -> AccessToken | None:
        found: TenantRecord | None = None
        candidate = token.encode()
        for known, rec in self._tokens.items():
            if hmac.compare_digest(candidate, known.encode()):
                found = rec
        if found is None:
            return None
        return AccessToken(
            token=token,
            client_id=found["tenant_id"],
            scopes=["notebooklm"],
            expires_at=None,
            subject=found["tenant_id"],
            claims={"profile": found["profile"]},
        )
