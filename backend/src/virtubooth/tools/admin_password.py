"""`virtubooth reset-admin-password`: for a forgotten admin password.

Works on the database directly (the server may keep running): `--from-env`
deletes the password set in the admin, so VB_ADMIN_PASSWORD logs in again;
otherwise it stores a new one (asked twice, or one line from stdin with
`--password-stdin`). Either way every admin session ends; the server checks the
database on every request, so it applies at once (open live streams end at
their next session check, within 30 s).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Sequence

from ..core.clock import now_iso
from ..core.passwords import MAX_LENGTH, MIN_LENGTH, hash_password
from ..repositories.app_settings import ADMIN_PASSWORD_KEY
from ..repositories.container import Repositories
from ._common import ToolError, add_data_dir_arg, open_repos, resolve_data_dir, run

PROG = "virtubooth reset-admin-password"
HELP = "reset the admin password (forgotten): back to VB_ADMIN_PASSWORD, or a new one"
DESCRIPTION = (
    "Reset the admin password and log out every admin.\n"
    "Without an option it asks for a new password twice."
)
EPILOG = (
    "examples:\n"
    "  virtubooth reset-admin-password --from-env\n"
    "  docker compose exec app virtubooth reset-admin-password --from-env\n"
    "  printf '%s\\n' \"$NEW_PASSWORD\" | virtubooth reset-admin-password --password-stdin"
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_data_dir_arg(parser)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--from-env",
        action="store_true",
        help="delete the password set in the admin: VB_ADMIN_PASSWORD logs in again",
    )
    mode.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the new password from the first line of standard input",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_arguments(p)
    return p


def reset(repos: Repositories, password: str | None) -> int:
    """Store `password` (None: delete the stored one) and end every admin
    session in one transaction. Returns how many sessions ended."""
    encoded = hash_password(password) if password is not None else None  # slow: before the tx
    at = now_iso()
    with repos.db.tx():
        if encoded is None:
            repos.app_settings.delete(ADMIN_PASSWORD_KEY)
        else:
            repos.app_settings.put_admin_password(encoded, by="cli", at=at)
        ended = repos.admin_sessions.delete_all(now=at)
        repos.audit.log(
            "cli",
            "admin.password_reset",
            details={"mode": "env" if encoded is None else "new", "sessions_ended": ended},
            at=at,
        )
    return ended


def _check(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise ToolError(f"the password needs at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise ToolError(f"the password may have at most {MAX_LENGTH} characters")
    return password


def _ask() -> str:
    password = _check(getpass.getpass("New admin password: "))
    if getpass.getpass("Repeat the new password: ") != password:
        raise ToolError("the two passwords are not the same")
    return password


def _main(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    # the database first: nobody types a password twice for a wrong --data-dir
    with open_repos(data_dir) as repos:
        if args.from_env:
            password = None
        elif args.password_stdin:
            password = _check(sys.stdin.readline().rstrip("\r\n"))
        else:
            password = _ask()
        ended = reset(repos, password)
    if password is None:
        print("admin password: VB_ADMIN_PASSWORD applies again")
    else:
        print("admin password: set (VB_ADMIN_PASSWORD no longer logs in)")
    print(f"admin sessions ended: {ended}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(_main, build_parser(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
