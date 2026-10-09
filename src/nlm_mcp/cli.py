"""Command line entry point: serve, auth passthrough, doctor."""

import argparse
import asyncio
import dataclasses
import os
import subprocess
import sys

from nlm_mcp.config import Settings


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


def _auth(args: argparse.Namespace) -> None:
    settings = _settings(args)
    base = [sys.executable, "-m", "notebooklm", "--profile", settings.profile]
    extra = [a for a in args.extra if a != "--"]
    if args.action == "login":
        argv = [*base, "login", *extra]
    else:
        argv = [*base, "auth", "check", *extra]
    proc = subprocess.run(argv, env=os.environ.copy(), check=False)
    sys.exit(proc.returncode)


_BANNER = """\
 .-.-.-.  nlm-mcp {version}
 |     |  MCP server for Google NotebookLM
 |     |  notebooks - sources - chat - artifacts
 '-----'
"""


def _doctor(args: argparse.Namespace) -> None:
    from nlm_mcp import __version__
    from nlm_mcp.backends.notebooklm_py import storage_path_for

    settings = _settings(args)
    storage = storage_path_for(settings.profile)
    print(_BANNER.format(version=__version__))
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
        help="authentication passthrough to the notebooklm CLI",
        description=(
            "login runs `notebooklm login`; status runs `notebooklm auth check`. "
            "Arguments after `--` are forwarded as they are."
        ),
    )
    auth.add_argument("action", choices=["login", "status"])
    auth.add_argument("--profile")
    auth.add_argument("extra", nargs=argparse.REMAINDER)
    auth.set_defaults(func=_auth)

    doctor = sub.add_parser("doctor", help="print resolved settings and session file state")
    doctor.add_argument("--profile")
    doctor.set_defaults(func=_doctor)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    args.func(args)
