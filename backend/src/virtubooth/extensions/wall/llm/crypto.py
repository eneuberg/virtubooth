"""The host's API keys at rest (PLAN-NIGHT N11), one per provider.

Settings key `x.llm.key` = `{v: 2, keys: {<provider>: {v: 1, provider, nonce,
ct, set_at, by}}}`: each key AES-256-GCM with a key derived from VB_SECRET_KEY
(HKDF-SHA256, salt `virtubooth`, info `llm-key-v1`), the provider id as
associated data. Switching the provider keeps the other providers' keys. Before
v2 the row held one record (`{v: 1, provider, …}`): it reads as that provider's
key and `migrate` rewrites it once. Nothing outside this module sees a plain
key except the provider client it is handed to; the API only ever answers
`{set, set_at, provider, valid}` per provider. A changed VB_SECRET_KEY makes a
stored key unreadable → `valid: false` („Schlüssel ungültig, bitte neu
eingeben“). Archives drop the row (tools/export.py SCRUBBED_SETTINGS_SQL).
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

from ....core.clock import now_iso
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


def _records(raw: Any) -> dict[str, dict[str, Any]]:
    """provider → its encrypted record, from the stored row (either shape)."""
    if not isinstance(raw, dict):
        return {}
    keys = raw.get("keys")
    if raw.get("v") == 2 and isinstance(keys, dict):
        return {str(p): r for p, r in keys.items() if isinstance(r, dict)}
    provider = raw.get("provider")
    if raw.get("v") == 1 and isinstance(provider, str):
        return {provider: raw}
    return {}


def stored_providers(app_settings: AppSettingsRepo) -> set[str]:
    """The providers with a stored key (readable or not; no secret needed)."""
    return set(_records(app_settings.get(KEY_KEY)))


class KeyStore:
    """Reads and writes `x.llm.key`. `secret` is VB_SECRET_KEY."""

    def __init__(self, app_settings: AppSettingsRepo, secret: str) -> None:
        self.app_settings = app_settings
        self._secret = secret

    def _all(self) -> dict[str, dict[str, Any]]:
        return _records(self.app_settings.get(KEY_KEY))

    def status(self, provider: str) -> KeyStatus:
        record = self._all().get(provider)
        if record is None:
            return KeyStatus(set=False, set_at=None, provider=provider, valid=False)
        try:
            decrypt(self._secret, record)
            valid = True
        except KeyUnreadable:
            valid = False
        set_at = record.get("set_at")
        return KeyStatus(
            set=True,
            set_at=set_at if isinstance(set_at, str) else None,
            provider=provider,
            valid=valid,
        )

    def load(self, provider: str) -> str | None:
        """The plain key for `provider`; None when none is stored for it or it
        cannot be decrypted."""
        record = self._all().get(provider)
        if record is None or record.get("provider") != provider:
            return None
        try:
            return decrypt(self._secret, record)
        except KeyUnreadable:
            return None

    def _save(self, records: dict[str, dict[str, Any]], at: str) -> None:
        if records:
            self.app_settings.put(KEY_KEY, {"v": 2, "keys": records}, at=at)
        else:
            self.app_settings.delete(KEY_KEY)

    def put(self, provider: str, key: str, *, by: str, at: str) -> None:
        """Store (or replace) `provider`'s key; the others stay."""
        record = encrypt(self._secret, provider, key)
        record.update({"set_at": at, "by": by})
        redact.remember(key)
        self._save({**self._all(), provider: record}, at)

    def clear(self, provider: str) -> bool:
        records = self._all()
        if records.pop(provider, None) is None:
            return False
        self._save(records, now_iso())
        return True

    def migrate(self) -> str | None:
        """A row from before v2 (one key with its provider) becomes that provider's
        entry. Returns the provider it was filed under, None when nothing to do."""
        raw = self.app_settings.get(KEY_KEY)
        if not isinstance(raw, dict) or raw.get("v") != 1:
            return None
        records = _records(raw)
        if not records:
            return None
        self._save(records, now_iso())
        return next(iter(records))
