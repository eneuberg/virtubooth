"""API errors with a machine code and a German message the UI can show as-is."""

from __future__ import annotations


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}

    def body(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}


def scan_qr() -> ApiError:
    return ApiError(404, "scan_qr", "Bitte scanne den QR-Code auf der Party, so geht das leider nicht.")


def needs_consent() -> ApiError:
    return ApiError(401, "needs_consent", "Bitte bestätige zuerst kurz die Hinweise.")


def banned() -> ApiError:
    return ApiError(403, "banned", "Dieses Gerät wurde für Uploads gesperrt.")


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        429,
        "rate_limited",
        "Langsam! Zu viele Anfragen. Warte kurz und versuch es nochmal.",
        headers={"Retry-After": str(retry_after)},
    )


def not_found(what: str = "Nicht gefunden.") -> ApiError:
    return ApiError(404, "not_found", what)


def bad_request(message: str, code: str = "bad_request") -> ApiError:
    return ApiError(400, code, message)


def admin_required() -> ApiError:
    return ApiError(401, "admin_required", "Bitte als Admin anmelden.")
