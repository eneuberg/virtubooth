"""The admin password hash (core/passwords.py): scrypt, encoded with its parameters."""

from __future__ import annotations

import base64
import hashlib

import pytest

from virtubooth.core.passwords import hash_password, verify_password

PASSWORD = "correct horse battery staple"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_round_trip_and_format():
    encoded = hash_password(PASSWORD)
    scheme, log_n, r, p, salt, digest = encoded.split("$")
    assert (scheme, log_n, r, p) == ("scrypt", "15", "8", "1")
    assert "=" not in salt + digest
    assert len(base64.urlsafe_b64decode(salt + "==")) == 16
    assert len(base64.urlsafe_b64decode(digest + "=")) == 32
    assert verify_password(PASSWORD, encoded)


def test_wrong_password():
    encoded = hash_password(PASSWORD)
    assert not verify_password(PASSWORD + " ", encoded)
    assert not verify_password("", encoded)


def test_two_hashes_of_one_password_differ():
    a, b = hash_password(PASSWORD), hash_password(PASSWORD)
    assert a != b
    assert verify_password(PASSWORD, a) and verify_password(PASSWORD, b)


def test_parameters_come_from_the_encoding():
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(PASSWORD.encode(), salt=salt, n=2**4, r=2, p=1, dklen=24)
    assert verify_password(PASSWORD, f"scrypt$4$2$1${b64(salt)}${b64(digest)}")


def test_unicode_and_lone_surrogates_never_raise():
    encoded = hash_password("Pässwörd-🎉-0123")
    assert verify_password("Pässwörd-🎉-0123", encoded)
    assert not verify_password("\ud800-not-utf8-able", encoded)
    assert verify_password("\ud800-x", hash_password("\ud800-x"))


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "plain-text-password",
        "scrypt$15$8$1$abc",  # too few fields
        "scrypt$15$8$1$abc$def$ghi",  # too many
        "bcrypt$15$8$1$c2FsdHNhbHRzYWx0c2FsdA$" + "A" * 43,
        "scrypt$x$8$1$c2FsdHNhbHRzYWx0c2FsdA$" + "A" * 43,
        "scrypt$-1$8$1$c2FsdHNhbHRzYWx0c2FsdA$" + "A" * 43,
        "scrypt$0$8$1$c2FsdHNhbHRzYWx0c2FsdA$" + "A" * 43,
        "scrypt$40$8$1$c2FsdHNhbHRzYWx0c2FsdA$" + "A" * 43,  # absurd cost
        "scrypt$15$8$999$c2FsdHNhbHRzYWx0c2FsdA$" + "A" * 43,
        "scrypt$15$8$1$$" + "A" * 43,  # no salt
        "scrypt$15$8$1$c2FsdHNhbHRzYWx0c2FsdA$",  # no hash
        "scrypt$15$8$1$c2FsdHNhbHRzYWx0c2FsdA$AAAA",  # hash too short
        "scrypt$15$8$1$not*base64!$" + "A" * 43,
        "scrypt$15$8$1$c2FsdHNhbHRzYWx0c2FsdA$" + "A" * 42 + "*",
        "scrypt$１５$8$1$c2FsdHNhbHRzYWx0c2FsdA$" + "A" * 43,  # fullwidth digits
    ],
)
def test_malformed_encodings_are_false(encoded):
    assert verify_password(PASSWORD, encoded) is False
