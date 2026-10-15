"""The API key never reaches a log record or a stored error text."""

from __future__ import annotations

import logging

import httpx2
import pytest

from virtubooth.extensions.wall.llm import admin_api, redact
from virtubooth.extensions.wall.llm.detect import DetectionRunner
from virtubooth.extensions.wall.llm.poller import poll_once
from virtubooth.extensions.wall.llm.providers.anthropic import AnthropicProvider
from virtubooth.extensions.wall.llm.providers.base import ProviderError

from ..conftest import ORIGIN
from ..llm_fakes import API_KEY, FakeProvider, add_guest, add_photo, add_property, setup_llm

BASE = "/api/x/wall/admin/llm"
OTHER_KEY = "QmlzdHJhbEtleVdpdGhvdXRQcmVmaXgxMjM0NTY"  # a Mistral-style key (no sk-)


@pytest.fixture(autouse=True)
def mounted(app):
    app.include_router(admin_api.router, prefix="/api/x/wall")
    redact.install()


def test_redact():
    assert redact.redact(f"bad key {API_KEY} here") == "bad key [redacted] here"
    assert redact.redact("sk-proj-abcdefgh12345") == "[redacted]"
    assert redact.redact("sk-short") == "sk-short"
    redact.remember(OTHER_KEY)
    assert OTHER_KEY not in redact.redact(f"x{OTHER_KEY}y")


def test_filter_masks_messages_args_and_tracebacks(caplog):
    caplog.set_level(logging.DEBUG)
    log = logging.getLogger("virtubooth.llm")
    log.warning("key is %s", API_KEY)
    log.warning(f"inline {API_KEY}")
    try:
        raise RuntimeError(f"boom {API_KEY}")
    except RuntimeError:
        log.exception("failed")
    logging.getLogger("virtubooth").error("root %s", {"k": API_KEY})
    assert caplog.records
    assert API_KEY not in caplog.text
    for record in caplog.records:
        assert API_KEY not in record.getMessage()


def test_key_never_in_logs_through_the_whole_path(admin, core, caplog):
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx2.Request) -> httpx2.Response:
        # an error body that echoes the key (some proxies do)
        return httpx2.Response(
            401,
            json={
                "type": "error",
                "error": {"type": "authentication_error", "message": f"invalid key {API_KEY}"},
            },
        )

    svc = setup_llm(core, detect={"local": True, "external": True})
    svc.provider_factory = lambda _pid, key: AnthropicProvider(
        key, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    svc.forget_provider()
    admin.put(f"{BASE}/key", json={"provider": "anthropic", "key": API_KEY}, headers=ORIGIN)
    admin.post(f"{BASE}/key/test", headers=ORIGIN)
    add_property(core)
    add_photo(core, add_guest(core))
    DetectionRunner(svc).run_once()
    poll_once(svc, force=True)
    assert caplog.records
    assert API_KEY not in caplog.text
    stored = " ".join(
        str(dict(r))
        for table in ("llm_polls", "photo_detection_runs", "llm_usage", "audit_log")
        for r in core.db.all(f"SELECT * FROM {table}")
    )
    assert API_KEY not in stored


def test_provider_errors_are_masked_before_storing(core):
    fake = FakeProvider(fail=ProviderError(f"rejected {API_KEY}", kind="bad_output"))
    svc = setup_llm(core, fake, detect={"local": True, "external": True})
    add_property(core)
    pid, _ = add_photo(core, add_guest(core))
    DetectionRunner(svc).run_once()
    result = poll_once(svc)
    assert result is not None and API_KEY not in (result.reason or "")
    run = core.db.one(
        "SELECT error FROM photo_detection_runs WHERE photo_id=? AND source='claude'", (pid,)
    )
    assert run["error"] == "rejected [redacted]"
    assert API_KEY not in core.db.one("SELECT error FROM llm_polls")["error"]


def test_loggers_made_after_install_are_masked_at_the_handler():
    """A child logger created later has no filter of its own; the root's
    handlers carry one."""
    records: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Keep()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        redact.install()
        late = logging.getLogger("some.library.made.later")
        late.setLevel(logging.INFO)
        late.warning("Authorization: Bearer %s", API_KEY)
    finally:
        root.removeHandler(handler)
    assert records and API_KEY not in records[-1].getMessage()
