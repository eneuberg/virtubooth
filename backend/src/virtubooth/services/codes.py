"""QR codes: the party's entrances (several, each with its own token).

- A scan (`?t=<token>`, middleware.py) looks the token up by hash among the
  active codes' current tokens (`entry`), sets the access cookie
  (`access_cookie`: the signed "<code id>.<token generation>") and counts the
  browser for that code (services/presence.py).
- `access_state` reads that cookie back: "current" while its code is active
  and still has that token, "stale" after the code was revoked or got a new
  token (api/deps.py `has_access` then lets only joined guests in), None
  without a valid cookie. Cookies from before the codes existed (a MAC of the
  single party token) count as code 1, generation 1.
- `ensure_seeded` creates code 1 from VB_PARTY_TOKEN (or a generated token) on
  the first start with codes, and adopts every guest and visitor from before.
  After that the database is the only source of tokens.
"""

from __future__ import annotations

import logging
import random
import re
from typing import TYPE_CHECKING, Literal

from starlette.requests import Request

from ..api.schemas.codes import AdminCode, CodesOut
from ..core import errors
from ..core.clock import now_iso
from ..core.security import ACCESS_COOKIE, constant_time_equals, sha256_hex
from ..db.database import Database
from ..domain import codes as dc
from ..repositories.container import Repositories
from .events import AdminEvents

if TYPE_CHECKING:
    from ..runtime import Core

log = logging.getLogger("virtubooth.codes")

SEED_KEY = "codes.seed"
SYSTEM_ACTOR = "system"
# the code a cookie from before the QR codes belongs to (the one seeding creates)
LEGACY_CODE_ID = 1
_ACCESS_PURPOSE = "access"
# the signed value of an access cookie: "<code id>.<token generation>"
_ACCESS_VALUE = re.compile(r"([1-9][0-9]{0,17})\.([1-9][0-9]{0,8})", re.ASCII)

ENV_TOKEN_CHANGED = (
    "VB_PARTY_TOKEN changed after QR code 1 was created from it; it no longer controls "
    "access. Manage QR codes in Admin → QR-Codes."
)
NOT_FOUND = "QR-Code nicht gefunden."
TOKEN_TAKEN = "Dieses Token hatte schon ein QR-Code. Ein Token wird nie zweimal vergeben."
CODE_REVOKED = "Dieser QR-Code ist gelöscht und lässt sich nicht mehr ändern."
INVALID_TARGET = "Unbekanntes Ziel."

AccessState = Literal["current", "stale"]


class CodesService:
    def __init__(
        self,
        core: Core,
        db: Database,
        repos: Repositories,
        events: AdminEvents,
        rng: random.Random | None = None,
    ) -> None:
        self.core = core
        self.db = db
        self.repos = repos
        self.events = events
        self.rng = rng or random.Random()

    # ------------------------------------------------------------ startup

    def ensure_seeded(self) -> None:
        """First start with QR codes (a new or an updated database): code 1
        from VB_PARTY_TOKEN, else with a generated token. Every guest and every
        visitor from before came through it. Idempotent; a database whose codes
        are all revoked is never seeded again."""
        env = self.core.settings.party_token
        env_token = env.get_secret_value() if env is not None else None
        with self.db.tx():
            if not self.repos.codes.any():
                self._seed(env_token)
        seed = self.repos.app_settings.get(SEED_KEY)
        if env_token is not None and seed.get("token_sha256") != sha256_hex(env_token):
            log.warning(ENV_TOKEN_CHANGED)

    def _seed(self, env_token: str | None) -> None:
        at = now_iso()
        token = env_token or self._new_token()
        animal = dc.pick_animal(self.repos.codes.animal_counts(), self.rng)
        code_id = self.repos.codes.create(
            animal=animal, token=token, target="", note="", at=at, by=SYSTEM_ACTOR
        )
        self.repos.codes.adopt_existing(code_id)
        source = "env" if env_token else "generated"
        self.repos.app_settings.put(
            SEED_KEY, {"token_sha256": sha256_hex(token), "at": at, "source": source}, at=at
        )
        self.repos.audit.log(
            SYSTEM_ACTOR,
            "code.create",
            f"code:{code_id}",
            {
                "name": dc.code_name(animal, code_id),
                "target": "",
                "note": "",
                "token": "VB_PARTY_TOKEN" if env_token else "erzeugt",
                "token_end": dc.token_end(token),
            },
            at=at,
        )
        log.info("created QR code %s (%s)", code_id, "from VB_PARTY_TOKEN" if env_token else source)

    # ------------------------------------------------------------ reading

    def views(self) -> CodesOut:
        stats = self.repos.codes.stats()
        codes = [self._view(c, stats.get(c.id)) for c in self.repos.codes.list()]
        active = sum(c.active for c in codes)
        return CodesOut(
            codes=codes,
            base_url=self.core.settings.public_base_url or None,
            active=active,
            revoked=len(codes) - active,
        )

    def view(self, code_id: int) -> AdminCode:
        code = self.repos.codes.get(code_id)
        if code is None:
            raise errors.not_found(NOT_FOUND)
        return self._view(code, self.repos.codes.stats().get(code.id))

    def _view(self, code: dc.PartyCode, stats: dc.CodeStats | None) -> AdminCode:
        loaded = code.target in self.core.extensions
        return AdminCode.of(code, stats or dc.CodeStats(), target_loaded=loaded)

    # ----------------------------------------------------------- changing

    def create(self, *, token: str | None, target: str, note: str, actor: str) -> AdminCode:
        target, note = self._check_target(target), self._check_note(note)
        custom = self._check_token(token)
        with self.db.tx():
            if custom is not None and self.repos.codes.token_taken(custom):
                raise errors.ApiError(409, "token_taken", TOKEN_TAKEN)
            value = custom or self._new_token()
            at = now_iso()
            animal = dc.pick_animal(self.repos.codes.animal_counts(), self.rng)
            code_id = self.repos.codes.create(
                animal=animal, token=value, target=target, note=note, at=at, by=actor
            )
            self.repos.audit.log(
                actor,
                "code.create",
                f"code:{code_id}",
                {
                    "name": dc.code_name(animal, code_id),
                    "target": target,
                    "note": note,
                    "token": "eigenes" if custom else "erzeugt",
                    "token_end": dc.token_end(value),
                },
                at=at,
            )
            view = self.view(code_id)
            self.events.code_changed(view, "created")
        return view

    def edit(
        self, code_id: int, *, target: str | None, note: str | None, actor: str
    ) -> tuple[AdminCode, bool]:
        """Change the target and/or the note (None = unchanged); (code, changed)."""
        with self.db.tx():
            code = self._active(code_id)
            new_target = code.target if target is None else target.strip()
            if new_target != code.target:
                new_target = self._check_target(new_target)
            new_note = code.note if note is None else self._check_note(note)
            if (new_target, new_note) == (code.target, code.note):
                return self.view(code_id), False
            at = now_iso()
            self.repos.codes.edit(code_id, target=new_target, note=new_note, at=at)
            self.repos.audit.log(
                actor,
                "code.edit",
                f"code:{code_id}",
                {"target": new_target, "note": new_note},
                at=at,
            )
            view = self.view(code_id)
            self.events.code_changed(view, "edited")
        return view, True

    def set_token(self, code_id: int, token: str | None, *, actor: str) -> AdminCode:
        """A new token (None = generate one). The old one stops working at
        once; browsers that scanned it keep access only once they joined."""
        with self.db.tx():
            self._active(code_id)
            custom = self._check_token(token)
            if custom is not None and self.repos.codes.token_taken(custom):
                raise errors.ApiError(409, "token_taken", TOKEN_TAKEN)
            value = custom or self._new_token()
            at = now_iso()
            self.repos.codes.set_token(code_id, value, at=at)
            self.repos.audit.log(
                actor,
                "code.token",
                f"code:{code_id}",
                {"token": "eigenes" if custom else "erzeugt", "token_end": dc.token_end(value)},
                at=at,
            )
            view = self.view(code_id)
            self.events.code_changed(view, "token")
        return view

    def revoke(self, code_id: int, *, actor: str) -> tuple[AdminCode, bool]:
        """„Löschen“: the token stops working, the row stays (a tombstone).
        (code, changed); revoking a revoked code changes nothing."""
        with self.db.tx():
            code = self.repos.codes.get(code_id)
            if code is None:
                raise errors.not_found(NOT_FOUND)
            if not code.active:
                return self.view(code_id), False
            at = now_iso()
            self.repos.codes.revoke(code_id, at=at, by=actor)
            self.repos.audit.log(
                actor, "code.revoke", f"code:{code_id}", {"name": code.name}, at=at
            )
            view = self.view(code_id)
            self.events.code_changed(view, "revoked")
        return view, True

    def _active(self, code_id: int) -> dc.PartyCode:
        code = self.repos.codes.get(code_id)
        if code is None:
            raise errors.not_found(NOT_FOUND)
        if not code.active:
            raise errors.ApiError(409, "code_revoked", CODE_REVOKED)
        return code

    def _new_token(self) -> str:
        while self.repos.codes.token_taken(token := dc.new_token()):
            pass  # 144 random bits: never, in practice
        return token

    @staticmethod
    def _check_token(token: str | None) -> str | None:
        """The custom token, stripped; None = generate one. 400 when unusable."""
        if token is None:
            return None
        token = token.strip()
        problem = dc.token_problem(token)
        if problem is not None:
            raise errors.bad_request(problem, "invalid_token")
        return token

    def _check_target(self, target: str) -> str:
        target = target.strip()
        if target and target not in self.core.extensions:
            raise errors.bad_request(INVALID_TARGET, "invalid_target")
        return target

    @staticmethod
    def _check_note(note: str) -> str:
        note = note.strip()
        problem = dc.note_problem(note)
        if problem is not None:
            raise errors.bad_request(problem, "invalid_note")
        return note

    # ------------------------------------------------------------ access

    def entry(self, token: str) -> dc.PartyCode | None:
        """The active code a scanned token opens, or None."""
        if not token or len(token) > dc.TOKEN_MAX:
            return None
        return self.repos.codes.by_token(token)

    def access_cookie(self, code: dc.PartyCode) -> str:
        """The `vb_access` value for a scan of `code`."""
        return self.core.signer.sign(_ACCESS_PURPOSE, f"{code.id}.{code.token_gen}")

    def access_state(self, request: Request) -> AccessState | None:
        """What the browser's access cookie is worth: "current" (its code is
        active and still has the token it scanned), "stale" (the code was
        revoked or got a new token since), None (no valid cookie)."""
        found = self._cookie_code(request)
        if found is None:
            return None
        code_id, gen = found
        code = self.repos.codes.get(code_id)
        if code is None:
            return None
        return "current" if code.active and code.token_gen == gen else "stale"

    def code_of_request(self, request: Request) -> int | None:
        """The code the browser's access cookie came from (a guest's code when
        it joins), or None."""
        found = self._cookie_code(request)
        if found is None or self.repos.codes.get(found[0]) is None:
            return None
        return found[0]

    def _cookie_code(self, request: Request) -> tuple[int, int] | None:
        """(code id, token generation) of a valid access cookie."""
        cookie = request.cookies.get(ACCESS_COOKIE)
        if not cookie:
            return None
        if "." not in cookie:
            return (LEGACY_CODE_ID, 1) if self._legacy_valid(cookie) else None
        value = self.core.signer.unsign(_ACCESS_PURPOSE, cookie)
        if value is None:
            return None
        match = _ACCESS_VALUE.fullmatch(value)
        return (int(match[1]), int(match[2])) if match else None

    def _legacy_valid(self, cookie: str) -> bool:
        """A cookie from before the QR codes: the MAC of the party token code 1
        was seeded with. Known while code 1 still has that token, later from
        VB_PARTY_TOKEN if it still is the seeded one."""
        code = self.repos.codes.get(LEGACY_CODE_ID)
        if code is None:
            return False
        token = code.token if code.token_gen == 1 else self._seeded_env_token()
        if token is None:
            return False
        mac = self.core.signer.mac(_ACCESS_PURPOSE, token)
        return constant_time_equals(cookie, mac)

    def _seeded_env_token(self) -> str | None:
        """VB_PARTY_TOKEN while it still is the token code 1 was seeded with."""
        env = self.core.settings.party_token
        if env is None:
            return None
        token = env.get_secret_value()
        seeded = self.repos.app_settings.get(SEED_KEY).get("token_sha256")
        return token if sha256_hex(token) == seeded else None
