"""`POST /test-image`: run the pipeline (and optionally the external AI) on an
image the admin uploads. Nothing is stored as a photo: the image lives in
memory for the request (and in D1's test job while the worker looks at it).

The body is multipart/form-data with `file` (a JPEG), `analyzers` ("all", a
comma list, or empty for none) and `external` ("0"/"1"). It is read with a
size cap first (the route is on the middleware's streamed list) and then split
with the standard library's MIME parser, so no multipart dependency is needed.
The image is validated like an upload (services/images.py: JPEG only, size
bounds, decompression-bomb guard) and re-encoded without metadata.
"""

from __future__ import annotations

import email.policy
from collections.abc import AsyncIterator
from dataclasses import dataclass
from email.parser import BytesParser
from typing import TYPE_CHECKING, cast

from ....core import errors
from ....core.errors import ErrorCode
from ....services.images import process_jpeg
from ....services.uploads import read_limited, too_large
from . import ports, pricing
from .detect import downscale
from .providers import BY_ID as PROVIDERS
from .providers.base import ProviderError, TokenUsage
from .schemas import (
    BoxOut,
    ExternalTestOut,
    MergedObjectOut,
    ObjectOut,
    TestImageOut,
    TestRunOut,
    UsageTotals,
)

if TYPE_CHECKING:
    from .service import LlmService

# a phone's full-size photo (4032 px) is fine here; MAX_IMAGE_PIXELS still caps decoding
MAX_SIDE = 4096
# the form fields and boundaries around the file
FORM_SLACK = 16 * 1024
MAX_FIELD = 1000
LOCAL_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class TestForm:
    __test__ = False  # not a pytest class

    image: bytes
    file_type: str | None
    analyzers: str
    external: bool


def _bad_form(message: str = "Ungültiges Formular.") -> errors.ApiError:
    return errors.bad_request(message, "invalid_image")


async def read_form(
    content_type: str, content_length: str, body: AsyncIterator[bytes], max_bytes: int
) -> TestForm:
    if content_type.split(";")[0].strip().lower() != "multipart/form-data":
        raise errors.ApiError(
            415, "unsupported_type", "Bitte das Bild als Formular (multipart/form-data) senden."
        )
    limit = max_bytes + FORM_SLACK
    if content_length.isdigit() and int(content_length) > limit:
        raise too_large()
    raw = await read_limited(body, limit)
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", "replace")
    msg = BytesParser(policy=email.policy.HTTP).parsebytes(head + raw)
    if not msg.is_multipart():
        raise _bad_form()
    fields: dict[str, bytes] = {}
    file_type: str | None = None
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or name in fields:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        if name == "file":
            file_type = part.get_content_type() if part.get("Content-Type") else None
        elif len(payload) > MAX_FIELD:
            raise _bad_form()
        fields[name] = payload
    image = fields.get("file")
    if not image:
        raise errors.bad_request("Bitte ein Bild auswählen.", "empty_upload")
    if len(image) > max_bytes:
        raise too_large()
    external = fields.get("external", b"0").decode("utf-8", "replace").strip()
    if external not in ("0", "1", ""):
        raise _bad_form("external muss 0 oder 1 sein.")
    return TestForm(
        image=image,
        file_type=file_type,
        analyzers=fields.get("analyzers", b"all").decode("utf-8", "replace").strip(),
        external=external == "1",
    )


def _analyzers(spec: str) -> list[str] | None:
    """None = all; [] = no local run; else the names (unknown → 400)."""
    if spec.lower() == "all":
        return None
    names = [n.strip() for n in spec.split(",") if n.strip()]
    if not names or names == ["none"]:
        return []
    known = ports.analyzer_names()
    for name in names:
        if name not in known:
            raise errors.bad_request(f"Unbekannte Analyse: {name[:40]}.", "unknown_analyzer")
    return names


def _objects(objs: list[ports.DetectedObject]) -> list[ObjectOut]:
    return [
        ObjectOut(
            label=o.label,
            label_de=o.label_de,
            score=o.score,
            box=BoxOut(x=o.box[0], y=o.box[1], w=o.box[2], h=o.box[3]) if o.box else None,
        )
        for o in objs
    ]


def _usage(model: str, usage: TokenUsage) -> UsageTotals:
    cost = pricing.cost_micro_usd(model, usage.input_tokens, usage.output_tokens)
    return UsageTotals(
        calls=1,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost / 1_000_000,
    )


def unavailable(code: str, message: str) -> errors.ApiError:
    status = 409 if code == "llm_budget_exhausted" else 400
    return errors.ApiError(status, cast(ErrorCode, code), message)


def run(svc: LlmService, form: TestForm) -> TestImageOut:
    """Blocking (worker round trip, provider call): run it in a thread."""
    from .service import Unavailable

    if form.file_type is not None and form.file_type != "image/jpeg":
        raise errors.ApiError(415, "unsupported_type", "Nur JPEG-Bilder sind erlaubt.")
    image = process_jpeg(form.image, max_side=MAX_SIDE, quality=90, thumb_side=64)
    names = _analyzers(form.analyzers)
    cfg = svc.config()
    if form.external:
        # fail fast, before the local run: a provider that can't see photos, no key,
        # or the budget is used up
        if not PROVIDERS[cfg.provider].vision:
            raise errors.bad_request(
                f"{PROVIDERS[cfg.provider].title} kann keine Fotos ansehen.", "llm_no_vision"
            )
        try:
            svc.provider(cfg)
        except Unavailable as exc:
            raise unavailable(exc.code, exc.message) from None
        reason = svc.blocked_reason(cfg)
        if reason is not None:
            raise unavailable("llm_budget_exhausted", reason)

    local: TestRunOut | None = None
    if names != []:
        try:
            result = ports.submit_test(
                svc.core, image.data, None if names is None else list(names), LOCAL_TIMEOUT_S
            )
        except ports.WorkerOff:
            raise errors.ApiError(
                409, "worker_off", "Die Analyse läuft gerade nicht (Worker aus)."
            ) from None
        except TimeoutError:
            # the worker is busy with a long queue or stuck: say so, keep the external part
            result = ports.TestRun(
                width=image.width,
                height=image.height,
                error="Keine Antwort von der Analyse (Zeitüberschreitung). Später noch einmal.",
            )
        local = TestRunOut(
            width=result.width,
            height=result.height,
            facts=result.facts,
            boxes=result.boxes,
            details=result.details,
            objects=_objects(result.objects),
            durations_ms=result.durations_ms,
            error=result.error,
            skipped=result.skipped,
        )

    external: ExternalTestOut | None = None
    if form.external:
        source = PROVIDERS[cfg.provider].source
        small = downscale(image.data, cfg.image_max_px)
        try:
            objs, usage = svc.call(
                "test", None, lambda p, m: p.detect(small, model=m, effort=cfg.effort), config=cfg
            )
            external = ExternalTestOut(
                source=source, model=cfg.model, objects=_objects(objs),
                usage=_usage(cfg.model, usage), error=None,
            )  # fmt: skip
        except Unavailable as exc:
            raise unavailable(exc.code, exc.message) from None
        except ProviderError as exc:
            external = ExternalTestOut(
                source=source, model=cfg.model, objects=[], usage=_usage(cfg.model, exc.usage),
                error=exc.message,
            )  # fmt: skip
    return TestImageOut(
        width=image.width, height=image.height, local=local, external=external,
        merged=_merged(local, external),
    )  # fmt: skip


def _detected(objs: list[ObjectOut]) -> list[ports.DetectedObject]:
    return [
        ports.DetectedObject(
            o.label, o.label_de, o.score, (o.box.x, o.box.y, o.box.w, o.box.h) if o.box else None
        )
        for o in objs
    ]


def _merged(local: TestRunOut | None, external: ExternalTestOut | None) -> list[MergedObjectOut]:
    """The merged list a photo with these results would get (local first)."""
    from ..enrich.merge import merge_lists

    lists: list[tuple[str, list[ports.DetectedObject]]] = []
    if local is not None:
        lists.append(("local", _detected(local.objects)))
    if external is not None:
        lists.append((external.source, _detected(external.objects)))
    ai = external.source if external is not None else None
    return [
        MergedObjectOut(
            idx=m.idx,
            label=m.label,
            label_de=m.label_de,
            score=m.score,
            box=BoxOut(x=m.box[0], y=m.box[1], w=m.box[2], h=m.box[3]) if m.box else None,
            sources=list(m.parts),
            local_pos=m.parts.get("local"),
            ai_pos=m.parts.get(ai) if ai else None,
        )
        for m in merge_lists(lists)
    ]
