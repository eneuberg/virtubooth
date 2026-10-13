"""CLI: `virtubooth serve` (default), `virtubooth gen-env`, `virtubooth export-openapi`,
`virtubooth reset-admin-password`."""

from __future__ import annotations

import argparse
import os
import secrets
import sys


def gen_env() -> str:
    return "\n".join(
        (
            "# virtubooth configuration. Keep this file secret.",
            f"VB_PARTY_TOKEN={secrets.token_urlsafe(18)}",
            f"VB_ADMIN_PASSWORD={secrets.token_urlsafe(15)}",
            f"VB_SECRET_KEY={secrets.token_urlsafe(48)}",
            "VB_PARTY_NAME=Party",
            "VB_INSTAGRAM_ACCOUNT=",
            "# public URL guests open (used for QR codes), e.g. https://party.example.com",
            "VB_PUBLIC_BASE_URL=http://localhost:8000",
            "# defaults to ./data; Docker pins /data",
            "# VB_DATA_DIR=./data",
            "# true behind an https reverse proxy",
            "VB_COOKIE_SECURE=auto",
            "# the built frontend (default: frontend/dist of this checkout); Docker pins it",
            "# VB_WEB_DIR=",
            "",
        )
    )


def check_forwarded_allow_ips(raw: str) -> str:
    """VB_FORWARDED_ALLOW_IPS / --forwarded-allow-ips, refusing `*`."""
    from .settings import ConfigError

    if any(entry.strip() == "*" for entry in raw.split(",")):
        raise ConfigError(
            "VB_FORWARDED_ALLOW_IPS must not be '*': the app would trust X-Forwarded-For "
            "from anyone who reaches its port, so every client could pick its own IP and "
            "get past the per-IP rate limits (the admin login's included). List the "
            "reverse proxy's address instead: its IP or subnet as the app sees it, e.g. "
            "127.0.0.1 for a proxy on this machine, the Docker network's gateway or "
            "subnet (172.16.0.0/12 covers Docker's default networks) for a proxy on the "
            "Docker host or in another container."
        )
    return raw


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="virtubooth")
    sub = parser.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="run the web server (default)")
    serve.add_argument("--host", default=os.environ.get("VB_HOST") or "127.0.0.1")
    serve.add_argument("--port", type=int, default=int(os.environ.get("VB_PORT") or "8000"))
    serve.add_argument(
        "--forwarded-allow-ips",
        default=os.environ.get("VB_FORWARDED_ALLOW_IPS") or "127.0.0.1",
        help="proxies whose X-Forwarded-For/-Proto are trusted (proxy IPs or subnets; '*' is refused)",
    )
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    sub.add_parser("gen-env", help="print a fresh .env with random secrets")
    export = sub.add_parser(
        "export-openapi", help="write the OpenAPI schema (JSON) for the frontend's typed client"
    )
    export.add_argument("-o", "--out", required=True, metavar="PATH", help="output file, or -")
    from .tools import admin_password

    reset = sub.add_parser(
        "reset-admin-password",
        help=admin_password.HELP,
        description=admin_password.DESCRIPTION,
        epilog=admin_password.EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    admin_password.add_arguments(reset)
    args = parser.parse_args(argv)

    if args.cmd == "gen-env":
        sys.stdout.write(gen_env())
        return
    if args.cmd == "export-openapi":
        from .openapi import export_openapi

        export_openapi(args.out)
        return
    if args.cmd == "reset-admin-password":
        # the subcommand is always the first argument (no global options)
        raise SystemExit(admin_password.main((sys.argv[1:] if argv is None else argv)[1:]))
    if args.cmd is None:
        args = parser.parse_args(["serve", *(argv or sys.argv[1:])])

    from .settings import ConfigError

    try:
        forwarded_allow_ips = check_forwarded_allow_ips(args.forwarded_allow_ips)
    except ConfigError as exc:
        parser.exit(2, f"virtubooth: {exc}\n")

    import uvicorn

    # one worker on purpose: rate limits and the event bus live in process memory
    uvicorn.run(
        "virtubooth.app:create_app_from_env",
        factory=True,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow_ips,
        reload=args.reload,
        server_header=False,
        # open SSE streams would otherwise hold `docker stop` until the kill timeout
        timeout_graceful_shutdown=5,
        access_log=True,
    )


if __name__ == "__main__":
    main()
