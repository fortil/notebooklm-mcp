"""Command line entry point: serve, auth passthrough, doctor."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from nlm_mcp.config import Settings

_BANNER_ART = (" .-.-.-.", " |     |", " |     |", " '-----'")


def _banner(*lines: str) -> str:
    rows = list(lines) + [""] * (len(_BANNER_ART) - len(lines))
    pairs = zip(_BANNER_ART, rows, strict=True)
    return "\n".join(a + (f"  {text}" if text else "") for a, text in pairs)


def _settings(args: argparse.Namespace) -> Settings:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    overrides: dict[str, object] = {}
    for attr in ("transport", "profile", "host", "port"):
        value = getattr(args, attr, None)
        if value is not None:
            overrides[attr] = value
    if overrides.get("transport") == "streamable-http" and not os.environ.get(
        "NLM_MCP_ALLOW_LOCAL_FILES"
    ):
        overrides["allow_local_files"] = False
    return dataclasses.replace(settings, **overrides)  # type: ignore[arg-type]


def _serve(args: argparse.Namespace) -> None:
    from nlm_mcp.server import create_server

    settings = _settings(args)
    try:
        settings.validate_for_serve()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    if settings.transport == "stdio":
        create_server(settings).run("stdio")
        return
    assert settings.tokens_file is not None
    from nlm_mcp.auth import StaticTokenVerifier  # lazy: auth.py lands in Step 12

    verifier = StaticTokenVerifier.from_file(settings.tokens_file)
    server = create_server(settings, token_verifier=verifier)
    asyncio.run(server.run_streamable_http_async(host=settings.host, port=settings.port))


def _sdk(settings: Settings, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "notebooklm", "--profile", settings.profile, *argv],
        capture_output=True,
        text=True,
    )


def _short(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home) :] if path.startswith(home) else path


def _auth_check(settings: Settings, extra: list[str]) -> tuple[int, dict[str, Any] | None]:
    proc = _sdk(settings, "auth", "check", "--json", *extra)
    try:
        data: dict[str, Any] | None = json.loads(proc.stdout) if proc.stdout.strip() else None
    except ValueError:
        data = None
    return proc.returncode, data


def _has_master_token(data: dict[str, Any]) -> bool:
    from notebooklm.paths import master_token_path_for

    storage = data.get("storage_path")
    return isinstance(storage, str) and master_token_path_for(Path(storage)).exists()


def _render_status(data: dict[str, Any]) -> bool:
    """Print a compact status block. Returns True when the session is usable."""
    from nlm_mcp import __version__

    checks: dict[str, Any] = data.get("checks") or {}
    psidts = (data.get("psidts") or {}).get("present") is True
    sid = checks.get("sid_cookie") is True
    token_fetch: bool | None = checks.get("token_fetch")
    ok = data.get("status") == "ok" or (sid and psidts and token_fetch is not False)

    print(_banner(f"nlm-mcp {__version__}", "auth status"))
    print(f"session   {'ok' if ok else 'broken'}")
    print(f"profile   {data.get('profile') or 'default'}")
    print(f"account   {(data.get('account') or {}).get('email') or 'unknown'}")
    print(f"storage   {_short(data.get('storage_path') or '(none)')}")
    sid_state = "ok" if sid else "missing"
    psidts_state = "ok" if psidts else "missing"
    print(f"cookies   SID {sid_state}, __Secure-1PSIDTS {psidts_state}")
    if token_fetch is True:
        print("token     fetched from Google ok")
    if _has_master_token(data):
        print("renewal   automatic (master token)")
    else:
        print("renewal   manual (run auth login again when it expires)")
    if not ok:
        found = (data.get("details") or {}).get("cookies_by_domain") or {}
        captured = [f"{name} ({domain})" for domain, names in found.items() for name in names]
        if captured:
            print(f"captured  {', '.join(captured)}")
        # only anonymous cookies on disk means a stale profile; start clean
        print(f"fix       nlm-mcp auth login{' --fresh' if captured and not sid else ''}")
    return ok


def _auth(args: argparse.Namespace) -> None:
    settings = _settings(args)
    extra = [a for a in (args.extra or []) if a != "--"]
    if args.action == "login":
        login = ["login"]
        if args.fresh:
            login.append("--fresh")
        if args.durable:
            if not args.account:
                sys.exit("nlm-mcp: --durable needs --account EMAIL")
            print(
                "note: --durable stores a Google master token on this machine (mode 0600). "
                "It grants full access to the account; keep it off shared machines."
            )
            login += ["--master-token", "--account", args.account]
        # The SDK owns the interactive browser flow; its output goes through
        # untouched and the verdict below is the last thing on screen. The
        # verdict uses a live token fetch: cookies on disk can look complete
        # and still be rejected by Google.
        proc = subprocess.run(
            [sys.executable, "-m", "notebooklm", "--profile", settings.profile, *login, *extra],
            check=False,
        )
        _, data = _auth_check(settings, ["--test"])
        if data is None:
            sys.exit(proc.returncode)
        print()
        sys.exit(0 if _render_status(data) else 1)
    # status
    if args.raw:
        sys.exit(_sdk(settings, "auth", "check", *extra).returncode)
    extra += ["--test"] if args.test else []
    code, data = _auth_check(settings, extra)
    if data is None:  # very old SDK without --json
        sys.exit(_sdk(settings, "auth", "check", *extra).returncode)
    sys.exit(0 if _render_status(data) else 1)


def _doctor(args: argparse.Namespace) -> None:
    from nlm_mcp import __version__
    from nlm_mcp.backends.notebooklm_py import storage_path_for

    settings = _settings(args)
    storage = storage_path_for(settings.profile)
    print(
        _banner(
            f"nlm-mcp {__version__}",
            "MCP server for Google NotebookLM",
            "notebooks - sources - chat - artifacts",
        )
    )
    print(f"profile:        {settings.profile}")
    print(f"sdk backend:    {settings.sdk_backend}")
    print(f"transport:      {settings.transport}")
    print(f"download dir:   {settings.download_dir}")
    print(f"usage log:      {settings.usage_log or '(unset)'}")
    print(f"tokens file:    {settings.tokens_file or '(unset)'}", end="")
    if settings.tokens_file is not None:
        print(f" ({'exists' if settings.tokens_file.exists() else 'missing'})", end="")
    print()
    print(f"storage file:   {storage} ({'exists' if storage.exists() else 'missing'})")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nlm-mcp", description="NotebookLM MCP server")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"])
    serve.add_argument("--profile")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=_serve)

    auth = sub.add_parser(
        "auth",
        help="log in with a Google account or check the saved session",
        description=(
            "login opens the browser and ends with a session verdict; status prints a "
            "compact local check (use --test for a live token fetch, --raw for the "
            "SDK's own output)."
        ),
    )
    auth.add_argument("action", choices=["login", "status"])
    auth.add_argument("--profile")
    auth.add_argument("--test", action="store_true", help="status: also fetch a token from Google")
    auth.add_argument("--raw", action="store_true", help="status: show the SDK's own output")
    auth.add_argument(
        "--fresh", action="store_true", help="login: discard the saved browser profile first"
    )
    auth.add_argument(
        "--durable",
        action="store_true",
        help="login: also save a master token so expired cookies renew on their own",
    )
    auth.add_argument("--account", help="login --durable: Google account email")
    auth.set_defaults(func=_auth, extra=[])

    doctor = sub.add_parser("doctor", help="print resolved settings and session file state")
    doctor.add_argument("--profile")
    doctor.set_defaults(func=_doctor)
    return parser


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    # everything after "--" goes to the SDK untouched (auth login -- --browser chrome)
    extra: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, extra = argv[:cut], argv[cut + 1 :]
    args = _parser().parse_args(argv)
    if extra:
        if args.command != "auth":
            sys.exit(f"nlm-mcp: '--' passthrough only works with auth, got: {' '.join(extra)}")
        args.extra = extra
    args.func(args)
