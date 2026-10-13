"""The admin password hash: stdlib scrypt, no extra dependency.

Encoded as `scrypt$<log2 n>$<r>$<p>$<salt>$<hash>`, salt and hash in urlsafe
base64 without padding, e.g. `scrypt$15$8$1$Zm9v...$YmFy...`. Verifying reads
the parameters from the encoded string, so stronger parameters later still
verify old hashes.

One computation takes about 32 MiB and a few dozen milliseconds. At most
`MAX_PARALLEL` run at once: a burst of login attempts from many addresses
(before the global lock trips) must not add up to gigabytes of RAM.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import threading

SCHEME = "scrypt"
LOG_N = 15
R = 8
P = 1
DKLEN = 32
SALT_BYTES = 16
MAXMEM = 64 * 1024 * 1024
MAX_PARALLEL = 2

# a new admin password (VB_ADMIN_PASSWORD has the same minimum; the login takes
# at most MAX_LENGTH)
MIN_LENGTH = 12
MAX_LENGTH = 256

# what verify accepts from an encoded string (anything else is malformed)
_MAX_LOG_N = 20
_MAX_R = 32
_MAX_P = 16

_slots = threading.BoundedSemaphore(MAX_PARALLEL)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    # strict: a character outside the urlsafe alphabet is an error, not skipped
    return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)


def _scrypt(password: str, salt: bytes, *, log_n: int, r: int, p: int, dklen: int) -> bytes:
    # surrogatepass: a lone surrogate from JSON hashes instead of raising
    secret = password.encode("utf-8", "surrogatepass")
    with _slots:
        return hashlib.scrypt(secret, salt=salt, n=2**log_n, r=r, p=p, dklen=dklen, maxmem=MAXMEM)


def hash_password(password: str) -> str:
    """A new encoded hash with a fresh random salt (never the same twice)."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(password, salt, log_n=LOG_N, r=R, p=P, dklen=DKLEN)
    return f"{SCHEME}${LOG_N}${R}${P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Whether `password` matches `encoded`. False for a malformed encoding
    (never raises on bad data)."""
    try:
        scheme, log_n_s, r_s, p_s, salt_s, hash_s = encoded.split("$")
        if scheme != SCHEME or not all(s.isascii() and s.isdigit() for s in (log_n_s, r_s, p_s)):
            return False
        log_n, r, p = int(log_n_s), int(r_s), int(p_s)
        if not (1 <= log_n <= _MAX_LOG_N and 1 <= r <= _MAX_R and 1 <= p <= _MAX_P):
            return False
        salt, expected = _unb64(salt_s), _unb64(hash_s)
        if not salt or not 16 <= len(expected) <= 64:
            return False
        digest = _scrypt(password, salt, log_n=log_n, r=r, p=p, dklen=len(expected))
    except (AttributeError, ValueError, TypeError, binascii.Error, MemoryError):
        return False
    return hmac.compare_digest(digest, expected)
