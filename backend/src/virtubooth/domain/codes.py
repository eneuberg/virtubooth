"""QR codes: the party's entrances. Pure rules, no persistence.

- A code's number is its id: never reused, rows are never deleted. „Löschen“
  revokes a code (a grey tombstone with its statistics).
- Its name is "<animal> <number>" („Gorilla 2“), frozen when it is created.
  ANIMALS leaves out the guest pseudonyms' animals (domain/names.py) and every
  word containing one, so „Giraffe 1“ never sits next to „Durstige Giraffe #1“.
- Every token a code ever had is kept (as a hash), so no token is handed out
  twice. Tokens are URL-safe: they go into `?t=` unencoded.
"""

from __future__ import annotations

import hashlib
import random
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

ANIMALS = (
    "Gorilla", "Elefant", "Löwe", "Tiger", "Leopard", "Gepard", "Jaguar", "Puma", "Luchs",
    "Wolf", "Dachs", "Marder", "Wiesel", "Hase", "Hamster", "Eichhörnchen", "Maulwurf",
    "Murmeltier", "Reh", "Hirsch", "Elch", "Rentier", "Bison", "Büffel", "Kamel", "Dromedar",
    "Nilpferd", "Tapir", "Okapi", "Antilope", "Gazelle", "Gnu", "Yak", "Pony", "Delfin", "Wal",
    "Orca", "Seehund", "Walross", "Seelöwe", "Hai", "Rochen", "Seepferdchen", "Seestern",
    "Hummer", "Krabbe", "Schildkröte", "Leguan", "Gecko", "Chamäleon", "Krokodil", "Waran",
    "Frosch", "Karakal", "Axolotl", "Papagei", "Kakadu", "Tukan", "Kolibri", "Pelikan",
    "Storch", "Kranich", "Reiher", "Schwan", "Adler", "Falke", "Bussard", "Uhu", "Rabe",
    "Spatz", "Meise", "Amsel", "Specht", "Strauß", "Emu", "Pfau", "Fasan", "Kiwi", "Biene",
    "Hummel", "Marienkäfer", "Falter", "Libelle", "Grille", "Schnecke", "Lemur", "Gibbon",
    "Schimpanse", "Mandrill", "Erdferkel", "Gürteltier", "Wombat", "Wallaby", "Schnabeltier",
    "Dingo", "Kojote", "Mungo", "Panther", "Ozelot", "Serval",
)  # fmt: skip

# custom tokens: the old VB_PARTY_TOKEN rule (every token this app ever printed
# can be registered) plus some variety
TOKEN_RE: Final = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
TOKEN_MIN_DISTINCT: Final = 6
# what an incoming ?t= can be at most before it is not worth hashing
TOKEN_MAX: Final = 128
# secrets.token_urlsafe(18): 24 characters, 144 bits
GENERATED_TOKEN_BYTES: Final = 18
NOTE_MAX: Final = 60
# how many characters of a token the audit log keeps
TOKEN_END_CHARS: Final = 4

TOKEN_INVALID = (
    "Das Token braucht 16 bis 128 Zeichen aus A–Z, a–z, 0–9, _ und - (ohne Leerzeichen)."
)
TOKEN_TOO_SIMPLE = (
    "Das Token ist zu einfach. Nimm mehr verschiedene Zeichen oder lass eins erzeugen."
)
NOTE_TOO_LONG = f"Die Notiz darf höchstens {NOTE_MAX} Zeichen haben."
NOTE_CONTROL = "Die Notiz darf keine Zeilenumbrüche oder Steuerzeichen enthalten."


def new_token() -> str:
    return secrets.token_urlsafe(GENERATED_TOKEN_BYTES)


def token_problem(token: str) -> str | None:
    """Why `token` can't be a custom token (German, for the admin), or None."""
    if not TOKEN_RE.match(token):
        return TOKEN_INVALID
    if len(set(token)) < TOKEN_MIN_DISTINCT:
        return TOKEN_TOO_SIMPLE
    return None


def note_problem(note: str) -> str | None:
    if len(note) > NOTE_MAX:
        return NOTE_TOO_LONG
    if any(ord(c) < 32 or 127 <= ord(c) < 160 for c in note):
        return NOTE_CONTROL
    return None


def token_hash(token: str) -> str:
    """SHA-256 hex: how tokens are looked up and remembered."""
    return hashlib.sha256(token.encode()).hexdigest()


def token_end(token: str) -> str:
    """The last characters, for the audit log (never the whole token)."""
    return token[-TOKEN_END_CHARS:]


def code_name(animal: str, code_id: int) -> str:
    return f"{animal} {code_id}"


def pick_animal(counts: Mapping[str, int], rng: random.Random) -> str:
    """A random animal among the least used ones (unused ones first)."""
    fewest = min(counts.get(a, 0) for a in ANIMALS)
    return rng.choice([a for a in ANIMALS if counts.get(a, 0) == fewest])


def entry_path(target: str, token: str) -> str:
    """The path a printed code opens: Start or an activity, with the token."""
    return f"/x/{target}/?t={token}" if target else f"/?t={token}"


@dataclass(frozen=True)
class PartyCode:
    id: int
    animal: str
    token: str
    token_gen: int
    target: str
    note: str
    created_at: str
    created_by: str
    updated_at: str
    revoked_at: str | None
    revoked_by: str | None

    @property
    def name(self) -> str:
        return code_name(self.animal, self.id)

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class CodeStats:
    """Per code: `scans` (valid scans), `people` (browsers that scanned it),
    `guests` (joined through it), `not_joined` (its browsers that never
    joined), `photos` (its guests' photos that aren't deleted), `active_now`
    (its guests not banned and seen within domain.overview.ACTIVE_MINUTES)."""

    scans: int = 0
    people: int = 0
    guests: int = 0
    not_joined: int = 0
    photos: int = 0
    active_now: int = 0
    first_scan_at: str | None = None
    last_scan_at: str | None = None
