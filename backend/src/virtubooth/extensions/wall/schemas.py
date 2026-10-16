"""Response and request shapes of the Live Wall (PLAN-WALL §4.2, §4.3)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, RootModel

from ...api.schemas.theme import PublicTheme
from .config import WallConfig

AnalysisState = Literal["pending", "running", "done", "failed", "skipped", "off"]
Via = Literal["password", "admin"]
EventId = Annotated[str, Field(description="`<epoch>-<n>`: the SSE `id:` line.")]

# ------------------------------------------------------------------ screen


class WallPhotoUrls(BaseModel):
    s: str = Field(description="400 px thumbnail.")
    m: str = Field(description="1280 px (cached derivative).")
    l: str = Field(description="The stored photo (≤ 2400 px).")  # noqa: E741


class WallPhoto(BaseModel):
    id: str = Field(description="Public photo id.")
    source: str = Field(description="Extension id.")
    seq: int
    taken_at: str
    width: int
    height: int
    author: str = Field(
        description="The name the wall shows: the display name, else „@instagram“ while "
        "the wall shows Instagram names, else the pseudonym."
    )
    instagram: str | None = Field(description="Only when the wall shows Instagram handles.")
    author_key: str = Field(description="Stable per guest, not reversible (12 chars).")
    urls: WallPhotoUrls
    facts: dict[str, float] = Field(description="people, faces, hands, smiles when analysed.")
    analysis: AnalysisState = Field(
        description="The photo analysis' state; `off`: the guest switched the analysis "
        "off, so no facts will come."
    )


class WallQr(BaseModel):
    url: str = Field(
        description="What the code opens: absolute with VB_PUBLIC_BASE_URL (or in the feed), "
        "else a path to resolve against the wall's own origin."
    )
    name: str = Field(description="The code's name, e.g. „Otter 1“.")


class WallFeed(BaseModel):
    config: WallConfig = Field(description="The look's colours are always set (theme filled in).")
    theme: PublicTheme = Field(description="The guest UI's theme (Erscheinungsbild).")
    event_name: str
    qr: WallQr | None = Field(description="The corner QR code (overlay.qr on), else null.")
    total: int = Field(description="Every photo visible on the wall.")
    photos: list[WallPhoto] = Field(description="Newest first, at most `limit`.")
    cursor: str = Field(description="Pass as `?since=` to the stream: nothing is missed.")
    server_time: str


class WallSessionOut(BaseModel):
    ok: Literal[True]
    via: Via


class WallLoginIn(BaseModel):
    password: str = Field(max_length=256)


class WallOk(BaseModel):
    ok: Literal[True]


class WallBox(BaseModel):
    x: float = Field(description="0..1 from the left of the photo")
    y: float = Field(description="0..1 from the top")
    w: float
    h: float


class WallWinnerObject(BaseModel):
    """The object the winner is about (the wall frames it)."""

    idx: int
    label_de: str
    value: float | None = Field(description="Its value (a property's score, else confidence).")
    box: WallBox | None = Field(
        description="On the shown photo (same crop as the analysed one); null: no frame."
    )


class WallComment(BaseModel):
    text: str = Field(description="The AI's comment on this winner (German, ≤ 160 chars).")
    emoji: str | None


class WallWinner(BaseModel):
    photo: WallPhoto
    value: float | None
    label: str = Field(
        description="German, headline and detail together, e.g. „7 Personen“, „um 19:42“, "
        "„Sonnenbrille · 0,93 Coolness“ (compatibility)."
    )
    headline: str = Field("", description="The object's name or the value text.")
    detail: str | None = Field(None, description="The value text when the headline is an object.")
    object_idx: int | None = Field(
        None, description="The object in the photo's list the value points at, if any."
    )
    object: WallWinnerObject | None = None
    comment: WallComment | None = Field(
        None, description="The AI's comment on this winner (only while the AI is ready)."
    )


class WallVerdict(BaseModel):
    """Deprecated: the best-ranked winner's comment (`winners[].comment`)."""

    text: str = Field(description="The AI's comment (German, ≤ 160 chars), shown below.")
    emoji: str | None
    photo_id: str | None = Field(description="Public id of the photo it is about, or null.")


class WallCategory(BaseModel):
    id: str
    emoji: str
    title: str
    line: str = Field(description="The host's subtitle, else the generated explanation.")
    winners: list[WallWinner] = Field(description="1–10, in order (best first).")
    verdict: WallVerdict | None = Field(
        None, description="Deprecated: the first winner's comment, when it has one."
    )


class WallCategoriesOut(BaseModel):
    categories: list[WallCategory] = Field(description="Enabled ones with winners, in order.")


# ------------------------------------------------------------------- admin


class WallPasswordState(BaseModel):
    set: bool
    changed_at: str | None


class WallPasswordIn(BaseModel):
    password: str = Field(max_length=256, description="6–256 characters.")


class WallSource(BaseModel):
    id: str
    title: str
    emoji: str


class WallCategoryInfo(BaseModel):
    id: str
    emoji: str
    title: str
    line: str
    enabled: bool
    available: bool
    reason: str | None = Field(description="Why it can't win anything (German), or null.")


class WallAdminOut(BaseModel):
    config: WallConfig
    defaults: WallConfig
    password: WallPasswordState
    wall_path: Literal["/livewall"]
    sources: list[WallSource] = Field(description="The upload extensions a wall can show.")
    categories: list[WallCategoryInfo]
    open_walls: int = Field(description="Wall screens connected right now.")
    event_name: str


# ------------------------------------------------------------------ events


class WallHelloData(BaseModel):
    config_rev: int
    server_time: str


class WallPhotoData(BaseModel):
    photo: WallPhoto


class WallRemoveData(BaseModel):
    ids: list[str]


class WallConfigData(BaseModel):
    config: WallConfig
    theme: PublicTheme
    event_name: str
    qr: WallQr | None


class WallEmptyData(BaseModel):
    pass


class WallByeData(BaseModel):
    reason: Literal["password", "logout"]


class WallHelloEvent(BaseModel):
    """Sent first on every connect (no id)."""

    type: Literal["hello"]
    data: WallHelloData


class WallPhotoAddEvent(BaseModel):
    """A photo became visible (after the delay, unhidden, unbanned)."""

    type: Literal["photo.add"]
    id: EventId
    data: WallPhotoData


class WallPhotoUpdateEvent(BaseModel):
    """A visible photo changed (e.g. its analysis finished)."""

    type: Literal["photo.update"]
    id: EventId
    data: WallPhotoData


class WallPhotoRemoveEvent(BaseModel):
    """Photos to take down at once (hidden, deleted, banned)."""

    type: Literal["photo.remove"]
    id: EventId
    data: WallRemoveData


class WallConfigEvent(BaseModel):
    type: Literal["config"]
    id: EventId
    data: WallConfigData


class WallCategoriesChangedEvent(BaseModel):
    """Refetch /livewall/api/categories."""

    type: Literal["categories.changed"]
    id: EventId
    data: WallEmptyData


class WallByeEvent(BaseModel):
    """This wall was logged out; the stream ends."""

    type: Literal["bye"]
    id: EventId
    data: WallByeData


class WallResyncEvent(BaseModel):
    """The missed events are gone (this stream's, or the server's own wall
    missed app events): refetch /livewall/api/feed."""

    type: Literal["stream.resync"]
    data: WallEmptyData


AnyWallEvent = Annotated[
    WallHelloEvent
    | WallPhotoAddEvent
    | WallPhotoUpdateEvent
    | WallPhotoRemoveEvent
    | WallConfigEvent
    | WallCategoriesChangedEvent
    | WallByeEvent
    | WallResyncEvent,
    Field(discriminator="type"),
]


class WallEvent(RootModel[AnyWallEvent]):
    """One message of the wall's event stream, discriminated by `type`."""
