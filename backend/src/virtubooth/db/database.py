"""SQLite access: one shared connection, serialized by a lock.

Party scale (tens of guests, a few writes per second at peak) never needs more.

Transactions nest: the outermost `tx()` is `BEGIN IMMEDIATE ... COMMIT`, inner
ones are savepoints. Repositories wrap their own writes in `tx()`; a service
wraps several repository calls (and the audit entry) in one outer `tx()`, which
makes them one atomic change. `on_commit(fn)` runs `fn` once the outermost
transaction committed (and drops it on rollback): services publish events and
delete files there, never before the change is durable.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import migrations

log = logging.getLogger("virtubooth.db")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        # only touched by the thread holding the lock
        self._depth = 0
        self._hooks: list[list[Callable[[], None]]] = []
        for pragma in (
            "journal_mode=WAL",
            "synchronous=NORMAL",
            "foreign_keys=ON",
            "busy_timeout=5000",
        ):
            self._conn.execute(f"PRAGMA {pragma}")
        self._migrate()

    def _migrate(self) -> None:
        """Upgrade the schema step by step up to SCHEMA_VERSION.

        Each step runs in its own write transaction and re-reads the version
        inside it, so a failing step leaves the database at the version before
        it, and a second process (a CLI tool next to the server) never runs a
        step twice. A newer database than this code knows is left alone.
        """
        with self._lock:
            if self._conn.execute("PRAGMA user_version").fetchone()[0] >= migrations.SCHEMA_VERSION:
                return
            for target, script in migrations.MIGRATIONS:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    version = self._conn.execute("PRAGMA user_version").fetchone()[0]
                    if version < target:
                        for statement in migrations.statements(script):
                            self._conn.execute(statement)
                        self._conn.execute(f"PRAGMA user_version={target}")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                self._conn.execute("COMMIT")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Write transaction (a savepoint when nested). Holds the lock throughout."""
        with self._lock:
            depth = self._depth
            savepoint = f"vb_sp{depth}"
            self._conn.execute("BEGIN IMMEDIATE" if depth == 0 else f"SAVEPOINT {savepoint}")
            self._depth += 1
            self._hooks.append([])
            try:
                yield self._conn
            except BaseException:
                self._depth -= 1
                self._hooks.pop()
                # some errors (disk full, I/O) end the transaction by themselves
                if self._conn.in_transaction:
                    if depth == 0:
                        self._conn.execute("ROLLBACK")
                    else:
                        self._conn.execute(f"ROLLBACK TO {savepoint}")
                        self._conn.execute(f"RELEASE {savepoint}")
                raise
            self._depth -= 1
            hooks = self._hooks.pop()
            if depth > 0:
                self._conn.execute(f"RELEASE {savepoint}")
                self._hooks[-1].extend(hooks)
                return
            try:
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
        # outside the lock: hooks may publish events or touch the file system
        for hook in hooks:
            try:
                hook()
            except Exception:
                log.exception("after-commit hook failed")

    def on_commit(self, hook: Callable[[], None]) -> None:
        """Run `hook` after the current transaction commits (now, if there is none)."""
        with self._lock:
            if self._depth:
                self._hooks[-1].append(hook)
                return
        hook()

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._conn.execute(sql, params).fetchone()
            return row

    def close(self) -> None:
        with self._lock:
            self._conn.close()
