"""The wall password uses the admin's scrypt helper (core/passwords.py); hashes
the wall's own helper stored before the merge still verify (same format)."""

from __future__ import annotations

from virtubooth.core.passwords import hash_password, verify_password

# made by the former extensions/wall/passwords.py for "geheim-123"
LEGACY_WALL_HASH = (
    "scrypt$15$8$1$_nSC_BFIn-FqtbDqfpDIPg$eAh-_H7xiLya6ZGMtfaiYn-Mtphng1mX76UxmsUcQxY"
)


def test_legacy_wall_hash_verifies():
    assert verify_password("geheim-123", LEGACY_WALL_HASH)
    assert not verify_password("geheim-124", LEGACY_WALL_HASH)


def test_new_hashes_have_the_wall_format():
    stored = hash_password("geheim-123")
    scheme, n, r, p, salt, digest = stored.split("$")
    assert (scheme, n, r, p) == ("scrypt", "15", "8", "1")
    assert len(salt) == 22 and len(digest) == 43  # 16 and 32 bytes, unpadded base64
    assert verify_password("geheim-123", stored)
