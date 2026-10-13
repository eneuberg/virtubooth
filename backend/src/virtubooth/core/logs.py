"""Access-log hygiene: never write the party token to the logs, skip health checks."""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote_plus

# for free-form messages; request targets are parsed (`mask_token`)
_TOKEN_RE = re.compile(r"([?&]t=)[^&\s\"]*")
MASK = "***"


def mask_token(target: str) -> str:
    """A request target (path?query) with the value of every `t` parameter
    masked. Keys are decoded the way Starlette's query parser does it
    (`%74=` and `t=` are the same parameter), so no spelling of the token
    entry gets through. Other parameters stay as they were sent."""
    path, sep, query = target.partition("?")
    if not sep:
        return target
    pairs = []
    for pair in query.split("&"):
        key, _, _value = pair.partition("=")
        pairs.append(f"{key}={MASK}" if unquote_plus(key) == "t" else pair)
    return f"{path}?{'&'.join(pairs)}"


class AccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple):
            if any(isinstance(a, str) and a.startswith("/healthz") for a in args):
                return False
            record.args = tuple(mask_token(a) if isinstance(a, str) else a for a in args)
        if isinstance(record.msg, str):
            record.msg = _TOKEN_RE.sub(rf"\1{MASK}", record.msg)
        return True


def install_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessLogFilter) for f in logger.filters):
        logger.addFilter(AccessLogFilter())
