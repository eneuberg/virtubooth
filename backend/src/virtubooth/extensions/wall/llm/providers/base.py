"""The provider interface: four calls, each answering with what it used.

Every call raises `ProviderError` on failure, carrying the tokens the provider
billed anyway (a refusal or an unreadable answer still costs) and a `kind`:
`auth`, `rate`, `network` and `server` are about the provider, not the photo
(the detection runner retries later); `model` (the provider does not know the
configured model), `bad_output`, `refused` and `other` are final for that
request.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..ports import DetectedObject

ErrorKind = Literal["auth", "rate", "network", "server", "model", "bad_output", "refused", "other"]
TRANSIENT: frozenset[ErrorKind] = frozenset({"auth", "rate", "network", "server"})


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


KEY_REJECTED = "Der API-Schlüssel wurde abgelehnt."
KEY_FORBIDDEN = (
    "Der API-Schlüssel hat keinen Zugriff (fehlende Berechtigung oder falsches Projekt)."
)
PING_PROMPT = "Antworte mit OK."


def model_unknown(model: str) -> str:
    return f"Das Modell „{model}“ gibt es bei diesem Anbieter nicht (Schlüssel funktioniert)."


class ProviderError(Exception):
    def __init__(self, message: str, *, kind: ErrorKind, usage: TokenUsage | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.kind: ErrorKind = kind
        self.usage = usage or TokenUsage()

    @property
    def transient(self) -> bool:
        return self.kind in TRANSIENT


@dataclass(frozen=True)
class PhotoLine:
    """One photo as text: its reference (`P<public id>`), the author's shown
    name, its object labels in list order and, for verdicts, property scores
    (aligned with the labels)."""

    ref: str
    author: str
    labels: tuple[str, ...]
    scores: Mapping[str, Sequence[float | None]] = field(default_factory=dict)


@dataclass(frozen=True)
class VerdictOut:
    text: str
    emoji: str | None
    photo: str | None
    object_index: int | None


class Provider(Protocol):
    """`effort`: config.effort („Denkaufwand“); providers without thinking ignore it.
    Thinking tokens are billed as output tokens and counted in `output_tokens`."""

    id: str

    def detect(
        self, image_jpeg: bytes, *, model: str, effort: str = "low"
    ) -> tuple[list[DetectedObject], TokenUsage]: ...

    def score(
        self,
        prompt: str,
        lines: Sequence[PhotoLine],
        *,
        model: str,
        relative: bool = False,
        effort: str = "low",
    ) -> tuple[dict[str, list[float | None]], TokenUsage]: ...

    def verdict(
        self, prompt: str, lines: Sequence[PhotoLine], *, model: str, effort: str = "low"
    ) -> tuple[VerdictOut, TokenUsage]: ...

    def ping(self, model: str) -> TokenUsage:
        """Check key and model as cheaply as the provider allows: its models list
        (free); a model not listed there is asked for one token. Raises
        ProviderError: `auth` (key rejected), `model` (model unknown), `network`
        (unreachable), `other` (e.g. wrong address/project)."""
        ...
