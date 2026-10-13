"""Request and response models of the QR codes (`/api/admin/codes`)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...domain import codes as dc

# generous: the service answers a too long token, note or target with its own
# German message (400) instead of a bare 422
_RAW_MAX = 1000


class CodeStats(BaseModel):
    """What happened through one code. Party scale, counted live."""

    scans: int = Field(description="Valid scans (every opening of its link).")
    people: int = Field(description="Browsers that opened it.")
    guests: int = Field(description="Guests who joined through it.")
    not_joined: int = Field(description="Its browsers that never joined.")
    photos: int = Field(description="Its guests' photos that aren't deleted.")
    active_now: int = Field(description="Its guests not banned and seen in the last 5 minutes.")
    online_seconds: int = Field(description="Its guests' online time added up (seconds).")
    online_now: int = Field(description="Its guests whose page is open and visible right now.")
    first_scan_at: str | None
    last_scan_at: str | None

    @classmethod
    def of(cls, stats: dc.CodeStats) -> CodeStats:
        return cls(
            scans=stats.scans,
            people=stats.people,
            guests=stats.guests,
            not_joined=stats.not_joined,
            photos=stats.photos,
            active_now=stats.active_now,
            online_seconds=stats.online_seconds,
            online_now=stats.online_now,
            first_scan_at=stats.first_scan_at,
            last_scan_at=stats.last_scan_at,
        )


class AdminCode(BaseModel):
    """One QR code, also when revoked („gelöscht“: `active` false)."""

    id: int = Field(description="The code's number; never reused.")
    name: str = Field(description="„<animal> <id>“, e.g. „Gorilla 2“; never changes.")
    animal: str
    token: str
    token_gen: int = Field(description="Counts the token changes (1 = the first token).")
    target: str = Field(description='"" = Start, else an activity id.')
    note: str
    entry_path: str = Field(
        description="What the code opens: `/?t=<token>` or `/x/<target>/?t=<token>` (`/` when "
        "the target is no longer loaded). The full URL is `(base_url ?? origin) + entry_path`."
    )
    active: bool
    created_at: str
    created_by: str
    updated_at: str
    revoked_at: str | None
    revoked_by: str | None
    stats: CodeStats

    @classmethod
    def of(cls, code: dc.PartyCode, stats: dc.CodeStats, *, target_loaded: bool) -> AdminCode:
        return cls(
            id=code.id,
            name=code.name,
            animal=code.animal,
            token=code.token,
            token_gen=code.token_gen,
            target=code.target,
            note=code.note,
            entry_path=dc.entry_path(code.target if target_loaded else "", code.token),
            active=code.active,
            created_at=code.created_at,
            created_by=code.created_by,
            updated_at=code.updated_at,
            revoked_at=code.revoked_at,
            revoked_by=code.revoked_by,
            stats=CodeStats.of(stats),
        )


class CodesOut(BaseModel):
    codes: list[AdminCode] = Field(description="Every code by number, revoked ones included.")
    base_url: str | None = Field(description="VB_PUBLIC_BASE_URL, or null.")
    active: int
    revoked: int


class CodeOut(BaseModel):
    code: AdminCode
    changed: bool


class CodeCreateIn(BaseModel):
    token: str | None = Field(
        default=None,
        max_length=_RAW_MAX,
        description="null = generate one; else 16-128 of A-Z a-z 0-9 _ - with at least 6 "
        "different characters, never used by any code before.",
    )
    target: str = Field(
        default="", max_length=_RAW_MAX, description='"" = Start, or an activity id.'
    )
    note: str = Field(
        default="", max_length=_RAW_MAX, description=f"At most {dc.NOTE_MAX} characters."
    )


class CodeEditIn(BaseModel):
    target: str | None = Field(default=None, max_length=_RAW_MAX, description="null = unchanged.")
    note: str | None = Field(default=None, max_length=_RAW_MAX, description="null = unchanged.")


class CodeTokenIn(BaseModel):
    token: str | None = Field(
        max_length=_RAW_MAX,
        description="null = generate one; else the same rules as when creating a code.",
    )
