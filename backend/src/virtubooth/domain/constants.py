"""Constants shared by every layer (one definition each)."""

from __future__ import annotations

import re
from typing import Final

# Photos of both built-in activities: exactly this size, 3:4 portrait. The
# browser captures it, the server re-checks it, the timelapse relies on it.
PHOTO_WIDTH: Final = 1080
PHOTO_HEIGHT: Final = 1440

# which camera took the photo (upload meta "facing")
FACINGS: Final = frozenset({"user", "environment"})

# The ban reason an identity gets when it joins showing a banned fingerprint.
# Such guests may just own the same phone model ("auto-banned").
AUTO_BAN_REASON: Final = "Gerät gesperrt (Fingerprint)"

# why a photo is hidden (photos.hidden_reason)
HIDDEN_BY_ADMIN: Final = "admin"
HIDDEN_BY_BAN: Final = "ban"

# why a guest's uploads are paused (users.uploads_paused_source)
PAUSE_ADMIN: Final = "admin"  # an admin paused this guest
PAUSE_NEW_GUEST_LOCK: Final = "new_guest_lock"  # joined while new guests were paused

# settings keys (JSON values)
UPLOAD_LOCK_KEY: Final = "upload_pause"  # new guests start with uploads paused
UPLOAD_STOP_KEY: Final = "upload_stop"  # nobody can upload

# ids in URLs
PHOTO_ID_PATTERN: Final = r"^[A-Za-z0-9_-]{8,32}$"
FP_HASH_PATTERN: Final = r"^[0-9a-f]{16,64}$"
EXT_ID_PATTERN: Final = r"^[a-z][a-z0-9-]{1,30}$"
META_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]{0,31}$"
PHOTO_ID_RE: Final = re.compile(PHOTO_ID_PATTERN)
EXT_ID_RE: Final = re.compile(EXT_ID_PATTERN)
META_KEY_RE: Final = re.compile(META_KEY_PATTERN)
# numeric ids (users, audit entries) stay below this
MAX_ID: Final = 2**62
