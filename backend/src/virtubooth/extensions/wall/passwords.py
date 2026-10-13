"""Password hashing for the Live Wall (stdlib scrypt).

Format: `scrypt$<log2 n>$<r>$<p>$<salt>$<hash>` with salt and hash in unpadded
URL-safe base64. Parameters n = 2^15, r = 8, p = 1, 32-byte hash, 16-byte salt:
~32 MiB and well under a second per check on a Raspberry Pi 5.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

N_LOG2 = 15
R = 8
P = 1
DKLEN = 32
SALT_BYTES = 16
MAXMEM = 64 * 1024 * 1024
# a stored hash with bigger parameters is refused (a tampered row must not
# make every login burn memory and CPU)
_MAX_N_LOG2 = 17


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n_log2: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=2**n_log2, r=r, p=p, maxmem=MAXMEM, dklen=DKLEN
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(password, salt, N_LOG2, R, P)
    return f"scrypt${N_LOG2}${R}${P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """True when `password` matches `stored`; False for anything malformed."""
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n_log2, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt, expected = _unb64(parts[4]), _unb64(parts[5])
    except ValueError:
        return False
    if not (1 <= n_log2 <= _MAX_N_LOG2 and 1 <= r <= 16 and 1 <= p <= 4 and expected):
        return False
    try:
        digest = _scrypt(password, salt, n_log2, r, p)
    except ValueError:  # parameters the platform refuses
        return False
    return hmac.compare_digest(digest, expected)
