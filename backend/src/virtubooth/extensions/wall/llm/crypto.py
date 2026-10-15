"""The host's API key at rest (PLAN-NIGHT N11).

Settings key `x.llm.key` = `{v: 1, provider, nonce, ct, set_at, by}`:
AES-256-GCM with a key derived from VB_SECRET_KEY (HKDF-SHA256, salt
`virtubooth`, info `llm-key-v1`), the provider id as associated data. Nothing
outside this module sees the plain key except the provider client it is
handed to; the API only ever answers `{set, set_at, provider, valid}`. A
changed VB_SECRET_KEY makes the stored key unreadable → `valid: false`
(„Schlüssel ungültig, bitte neu eingeben“). Archives drop the row
(tools/export.py SCRUBBED_SETTINGS_SQL).
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from typing import Any, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ....repositories.app_settings import AppSettingsRepo
from . import redact

KEY_KEY: Final = "x.llm.key"
MAX_KEY_LEN: Final = 400
_NO_SPACE = re.compile(r"^\S+$")


class KeyUnreadable(Exception):
    """The stored key cannot be decrypted (VB_SECRET_KEY changed, tampered row)."""


@dataclass(frozen=True)
class KeyStatus:
    set: bool
    set_at: str | None
    provider: str | None
    valid: bool


def check_format(key: str) -> str | None:
    """A German problem with the key's form, None when it is fine (loose on
    purpose: providers change their key formats)."""
    if not key:
        return "Bitte einen API-Schlüssel eingeben."
    if len(key) > MAX_KEY_LEN:
        return f"Der Schlüssel ist zu lang (höchstens {MAX_KEY_LEN} Zeichen)."
    if not _NO_SPACE.match(key):
        return "Der Schlüssel darf keine Leerzeichen oder Zeilenumbrüche enthalten."
    return None


def _aead(secret: str) -> AESGCM:
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"virtubooth", info=b"llm-key-v1"
    ).derive(secret.encode("utf-8"))
    return AESGCM(derived)


def encrypt(secret: str, provider: str, key: str) -> dict[str, Any]:
    nonce = os.urandom(12)
    ct = _aead(secret).encrypt(nonce, key.encode("utf-8"), provider.encode("utf-8"))
    return {
        "v": 1,
        "provider": provider,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ct).decode("ascii"),
    }


def decrypt(secret: str, record: dict[str, Any]) -> str:
    try:
        if record.get("v") != 1:
            raise KeyUnreadable("unknown key record version")
        provider = str(record["provider"])
        nonce = base64.b64decode(record["nonce"], validate=True)
        ct = base64.b64decode(record["ct"], validate=True)
        plain = _aead(secret).decrypt(nonce, ct, provider.encode("utf-8")).decode("utf-8")
    except (InvalidTag, KeyError, ValueError, TypeError) as exc:
        raise KeyUnreadable("the stored key cannot be decrypted") from exc
    redact.remember(plain)
    return plain


class KeyStore:
    """Reads and writes `x.llm.key`. `secret` is VB_SECRET_KEY."""

    def __init__(self, app_settings: AppSettingsRepo, secret: str) -> None:
        self.app_settings = app_settings
        self._secret = secret

    def status(self) -> KeyStatus:
        record = self.app_settings.get(KEY_KEY)
        if not record:
            return KeyStatus(set=False, set_at=None, provider=None, valid=False)
        try:
            decrypt(self._secret, record)
            valid = True
        except KeyUnreadable:
            valid = False
        set_at, provider = record.get("set_at"), record.get("provider")
        return KeyStatus(
            set=True,
            set_at=set_at if isinstance(set_at, str) else None,
            provider=provider if isinstance(provider, str) else None,
            valid=valid,
        )

    def load(self, provider: str) -> str | None:
        """The plain key for `provider`; None when none is stored, it belongs to
        another provider or cannot be decrypted."""
        record = self.app_settings.get(KEY_KEY)
        if not record or record.get("provider") != provider:
            return None
        try:
            return decrypt(self._secret, record)
        except KeyUnreadable:
            return None

    def put(self, provider: str, key: str, *, by: str, at: str) -> None:
        record = encrypt(self._secret, provider, key)
        record.update({"set_at": at, "by": by})
        redact.remember(key)
        self.app_settings.put(KEY_KEY, record, at=at)

    def clear(self) -> bool:
        return self.app_settings.delete(KEY_KEY)
