"""Keep API keys out of logs and stored error texts.

`redact(text)` masks everything that looks like a key (`sk-…`, also
`sk-ant-…`) and every key registered with `remember()` (the decrypted key in
use, whatever its format: Mistral keys have no prefix). `install()` puts a
filter doing the same on the `virtubooth` loggers and on the loggers of the
HTTP stack the provider SDKs use.
"""

from __future__ import annotations

import logging
import re
import threading

MASK = "[redacted]"
_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
_known: set[str] = set()
_lock = threading.Lock()

# the loggers a key could reach: ours and the SDKs' HTTP layers
LOGGERS = ("virtubooth", "virtubooth.llm", "anthropic", "httpx2", "httpcore2", "httpx", "httpcore")


def remember(secret: str) -> None:
    """Mask this exact string from now on (keys shorter than 8 characters are
    not real keys and would mask ordinary words)."""
    if len(secret) >= 8:
        with _lock:
            _known.add(secret)


def redact(text: str) -> str:
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for secret in known:
        if secret in text:
            text = text.replace(secret, MASK)
    return _KEY_RE.sub(MASK, text)


def _clean(value: object) -> object:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, BaseException):
        return redact(str(value))
    return value


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        elif isinstance(record.msg, BaseException):
            record.msg = redact(str(record.msg))
        if isinstance(record.args, tuple):
            record.args = tuple(_clean(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _clean(v) for k, v in record.args.items()}
        if record.exc_info and record.exc_info[1] is not None:
            # the traceback text is made later by the handler: render it now, masked
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def install() -> None:
    """Idempotent. A logger's filter only sees the records logged on that very
    logger, so: the provider SDKs are imported first (their module loggers
    exist then), every `virtubooth.*`/SDK logger that exists gets the filter,
    and so does every handler of the root and uvicorn loggers (they see the
    records of loggers made later, too)."""
    from .providers import anthropic as _anthropic  # noqa: F401
    from .providers import mistral as _mistral  # noqa: F401

    names = set(LOGGERS)
    names.update(
        n
        for n in logging.root.manager.loggerDict
        if n.startswith(("virtubooth.", "anthropic.", "httpx", "httpcore"))
    )
    for name in names:
        _add(logging.getLogger(name))
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            _add(handler)


def _add(target: logging.Filterer) -> None:
    if not any(isinstance(f, RedactFilter) for f in target.filters):
        target.addFilter(RedactFilter())
