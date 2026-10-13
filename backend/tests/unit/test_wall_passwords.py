"""The wall password hash (stdlib scrypt, PLAN-WALL D4)."""

from __future__ import annotations

import pytest

from virtubooth.extensions.wall.passwords import hash_password, verify_password


def test_hash_format_and_verify():
    stored = hash_password("geheim-123")
    scheme, n, r, p, salt, digest = stored.split("$")
    assert (scheme, n, r, p) == ("scrypt", "15", "8", "1")
    assert len(salt) == 22 and len(digest) == 43  # 16 and 32 bytes, unpadded base64
    assert verify_password("geheim-123", stored)
    assert not verify_password("geheim-124", stored)
    assert not verify_password("", stored)


def test_salted():
    assert hash_password("same") != hash_password("same")


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "",
        "plain",
        "bcrypt$15$8$1$AAAA$BBBB",
        "scrypt$15$8$1$AAAA",
        "scrypt$x$8$1$AAAA$BBBB",
        "scrypt$15$8$1$!!!!$BBBB",
        "scrypt$15$8$1$AAAA$",
        # parameters a tampered row could use to burn memory or CPU
        "scrypt$30$8$1$AAAAAAAAAAAAAAAAAAAAAA$" + "A" * 43,
        "scrypt$15$99$1$AAAAAAAAAAAAAAAAAAAAAA$" + "A" * 43,
        "scrypt$15$8$50$AAAAAAAAAAAAAAAAAAAAAA$" + "A" * 43,
    ],
)
def test_malformed_hashes_never_match(stored):
    assert not verify_password("geheim-123", stored)
