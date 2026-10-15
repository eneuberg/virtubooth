"""API errors: a machine code plus a German message the UI shows as-is.

Every error the API returns is `{"error": <ErrorCode>, "message": <German>}`
(`ErrorBody`). `ErrorCode` lists every code the server produces; the frontend
gets it as a TypeScript union through the exported OpenAPI schema. Framework
errors are `http_<status>` (in practice 404 for unknown /api paths and 405).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ErrorCode = Literal[
    # access and identity
    "scan_qr",
    "needs_consent",
    "banned",
    "consent_outdated",
    "invalid_instagram",
    "join_closed",
    "invalid_display_name",
    "display_name_taken",
    # live wall
    "wall_login_required",
    "wall_no_password",
    "wall_password_too_short",
    "invalid_wall_config",
    # wall categories and analysis
    "invalid_category",
    "category_exists",
    "invalid_analyzer_settings",
    "worker_off",
    "ml_missing",
    # uploads
    "uploads_paused",
    "uploads_stopped",
    "unsupported_type",
    "too_large",
    "invalid_meta",
    "empty_upload",
    "invalid_image",
    "photo_limit",
    "storage_full",
    # poster
    "invalid_pdf",
    "invalid_layout",
    "no_template",
    # admin
    "admin_required",
    "wrong_password",
    "login_locked",
    "invalid_filter",
    "unknown_analyzer",
    "invalid_cursor",
    "no_fingerprint",
    "restore_required",
    # admin settings
    "invalid_event_name",
    "invalid_public_address",
    "invalid_theme",
    "password_too_short",
    "password_unchanged",
    "no_filter_enabled",
    "unknown_filter",
    # admin exports
    "export_not_ready",
    "export_running",
    # QR codes
    "invalid_token",
    "token_taken",
    "code_revoked",
    "invalid_target",
    "invalid_note",
    # external AI (LLM)
    "invalid_llm_config",
    "llm_not_configured",
    "llm_key_invalid",
    "llm_budget_exhausted",
    "invalid_property",
    "property_exists",
    # request guards
    "bad_origin",
    "length_required",
    "rate_limited",
    "invalid_request",
    "not_found",
    # framework (http_<status>)
    "http_404",
    "http_405",
]


class ErrorBody(BaseModel):
    """Every error response."""

    error: ErrorCode = Field(description="Machine-readable error code.")
    message: str = Field(description="German text for the guest or admin, shown as-is.")
    field: str | None = Field(
        default=None,
        description="The form field a 400 is about, when the answer names one "
        "(e.g. `invalid_category`: title, line, where, by, count, verdict, ...).",
    )


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: ErrorCode,
        message: str,
        *,
        headers: dict[str, str] | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code: ErrorCode = code
        self.message = message
        self.headers = headers or {}
        self.field = field

    def body(self) -> dict[str, str]:
        out = {"error": self.code, "message": self.message}
        if self.field is not None:
            out["field"] = self.field
        return out


# ------------------------------------------------------------ factories


def scan_qr() -> ApiError:
    return ApiError(
        404, "scan_qr", "Bitte scanne den QR-Code auf der Party, so geht das leider nicht."
    )


def needs_consent() -> ApiError:
    return ApiError(401, "needs_consent", "Bitte bestätige zuerst kurz die Hinweise.")


def banned() -> ApiError:
    """For uploads: the guest's device is banned."""
    return ApiError(403, "banned", "Dieses Gerät wurde für Uploads gesperrt.")


def device_banned() -> ApiError:
    """Same code as `banned`, for everything that is not an upload (e.g. the
    Instagram editor): the message must not talk about uploads."""
    return ApiError(403, "banned", "Dieses Gerät ist gesperrt.")


def uploads_paused() -> ApiError:
    return ApiError(
        403,
        "uploads_paused",
        "Uploads sind für dich gerade pausiert. Die Gastgeber schalten sie bald wieder frei.",
    )


def uploads_stopped() -> ApiError:
    return ApiError(
        403, "uploads_stopped", "Uploads sind gerade kurz gestoppt – gleich geht's weiter."
    )


def photo_limit() -> ApiError:
    """The guest keeps VB_MAX_PHOTOS_PER_GUEST photos already (deleted ones don't count)."""
    return ApiError(
        403,
        "photo_limit",
        "Du hast schon sehr viele Fotos gemacht – mehr passen leider nicht. "
        "Lösche ein paar unter „Deine Bilder“, dann geht's weiter.",
    )


def storage_full() -> ApiError:
    """The server's disk is almost full (VB_MIN_FREE_MB): no upload is stored.
    503 with Retry-After: the guest's outbox keeps the photo and tries again later."""
    return ApiError(
        503,
        "storage_full",
        "Der Speicher auf dem Server ist fast voll. Sag bitte den Gastgebern Bescheid.",
        headers={"Retry-After": "300"},
    )


def join_closed() -> ApiError:
    """The host stopped new joins for a moment (already joined guests are not affected)."""
    return ApiError(
        403, "join_closed", "Gerade kann niemand neu beitreten. Versuch es gleich noch mal."
    )


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        429,
        "rate_limited",
        "Langsam! Zu viele Anfragen. Warte kurz.",
        headers={"Retry-After": str(retry_after)},
    )


def not_found(what: str = "Nicht gefunden.") -> ApiError:
    return ApiError(404, "not_found", what)


def bad_request(message: str, code: ErrorCode) -> ApiError:
    return ApiError(400, code, message)


def admin_required() -> ApiError:
    return ApiError(401, "admin_required", "Bitte als Admin anmelden.")


def bad_origin() -> ApiError:
    return ApiError(403, "bad_origin", "Anfrage von fremder Seite abgelehnt.")


def invalid_request() -> ApiError:
    return ApiError(422, "invalid_request", "Ungültige Anfrage.")


# ----------------------------------------------------- OpenAPI responses

_DESCRIPTIONS = {
    400: "Invalid input (see `error`)",
    401: "Needs consent or an admin session",
    403: "Forbidden: banned, paused, stopped, joining closed or a foreign Origin (CSRF)",
    404: "Not found, or no party access (`scan_qr`)",
    405: "Method not allowed",
    409: "Conflict",
    411: "Content-Length required",
    413: "Request too large",
    415: "Unsupported media type",
    422: "Request validation failed (`invalid_request`)",
    429: "Rate limited (`Retry-After` header)",
    503: "The server's disk is almost full (`storage_full`, `Retry-After` header)",
}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """`responses=` for a router: these statuses answer with `ErrorBody`."""
    return {
        status: {"model": ErrorBody, "description": _DESCRIPTIONS.get(status, "Error")}
        for status in sorted(statuses)
    }


def json_error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Like `error_responses`, spelled out as JSON for routes whose success is
    not JSON (FastAPI would document the errors with the route's media type)."""
    schema = {"$ref": "#/components/schemas/ErrorBody"}
    return {
        status: {
            "description": _DESCRIPTIONS.get(status, "Error"),
            "content": {"application/json": {"schema": schema}},
        }
        for status in sorted(statuses)
    }
