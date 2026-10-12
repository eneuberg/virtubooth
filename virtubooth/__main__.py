"""CLI: `virtubooth serve` (default) and `virtubooth gen-env`."""

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
            "",
        )
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="virtubooth")
    sub = parser.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="run the web server (default)")
    serve.add_argument("--host", default=os.environ.get("VB_HOST") or "127.0.0.1")
    serve.add_argument("--port", type=int, default=int(os.environ.get("VB_PORT") or "8000"))
    serve.add_argument(
        "--forwarded-allow-ips",
        default=os.environ.get("VB_FORWARDED_ALLOW_IPS") or "127.0.0.1",
        help="proxies whose X-Forwarded-For/-Proto are trusted ('*' only inside a private network)",
    )
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    sub.add_parser("gen-env", help="print a fresh .env with random secrets")
    args = parser.parse_args(argv)

    if args.cmd == "gen-env":
        sys.stdout.write(gen_env())
        return
    if args.cmd is None:
        args = parser.parse_args(["serve", *(argv or sys.argv[1:])])

    import uvicorn

    # one worker on purpose: rate limits and the event bus live in process memory
    uvicorn.run(
        "virtubooth.app:create_app_from_env",
        factory=True,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips=args.forwarded_allow_ips,
        reload=args.reload,
        server_header=False,
        # open SSE streams would otherwise hold `docker stop` until the kill timeout
        timeout_graceful_shutdown=5,
        access_log=True,
    )


if __name__ == "__main__":
    main()
