"""The theme: colours of the guest UI and the Live Wall, set in Allgemeines.

Stored as `x.theme` = {preset, colors, rev, updated_at, by}; absent = „Neon
Nacht“. Every guest page (index.html, gate.html, wall.html) links
`/api/theme.css?v=<rev>` in its <head> (WebFrontend.theme_head), so the
colours are there before the first paint without an inline style (CSP).
The guest app re-reads `/api/theme` when it becomes visible again, and open
walls get a `config` event (`theme.changed`, in-process only), so a change
shows without a reload of the server.

Readability is checked here: `text` and `text_muted` on `background` and on
`surface` need 4.5:1, else 400 `invalid_theme` names the pair.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from ..api.schemas.theme import (
    AdminTheme,
    AdminThemeOut,
    PublicTheme,
    ThemeColors,
    ThemeIn,
    ThemePreset,
)
from ..core import errors
from ..core.clock import now_iso

if TYPE_CHECKING:
    from ..db.database import Database
    from ..repositories.container import Repositories
    from .events import AdminEvents

THEME_KEY: Final = "x.theme"
THEME_EVENT: Final = "theme.changed"
MIN_CONTRAST: Final = 4.5

NEON_NACHT = ThemeColors(
    background="#1b1b1a",
    surface="#252229",
    depth="#1a0733",
    primary="#c026ff",
    secondary="#eba6c6",
    tertiary="#b6b6d8",
    accent="#ff2fb0",
    highlight="#cee4f7",
    hit="#b6ff3c",
    text="#fcf2f9",
    text_muted="#bdb3c4",
)
# the "Kontaktbogen" colours of the first rebuild, exactly
KLASSISCH = ThemeColors(
    background="#2b0f0c",
    surface="#3b1712",
    depth="#1c0806",
    primary="#ffa630",
    secondary="#fbefe9",
    tertiary="#c9b8b0",
    accent="#ff7a66",
    highlight="#ffbb5c",
    hit="#84d49b",
    text="#fbefe9",
    text_muted="#c9b8b0",
)
PRESETS: Final = (
    ThemePreset(id="neon_nacht", label="Neon Nacht", colors=NEON_NACHT),
    ThemePreset(id="klassisch", label="Klassisch", colors=KLASSISCH),
)
DEFAULT_PRESET: Final = PRESETS[0]

LABELS: Final = {
    "background": "Hintergrund",
    "surface": "Fläche",
    "text": "Text",
    "text_muted": "Nebentext",
}
# (foreground, background) pairs that must stay readable
CHECKED_PAIRS: Final = (
    ("text", "background"),
    ("text", "surface"),
    ("text_muted", "background"),
    ("text_muted", "surface"),
)


# --------------------------------------------------------------- colour maths


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    """WCAG relative luminance of `#rrggbb`."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two `#rrggbb` colours (1 … 21)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable_on(fill: str, colors: ThemeColors) -> str:
    """Text colour for a `fill`: the first of background, depth, text, black,
    white with 4.5:1, else the one with the most contrast. (Mirrored in
    frontend/src/styles/theme.ts `readableOn`.)"""
    candidates = (colors.background, colors.depth, colors.text, "#000000", "#ffffff")
    for c in candidates:
        if contrast(fill, c) >= MIN_CONTRAST:
            return c
    return max(candidates, key=lambda c: contrast(fill, c))


def mix(a: str, b: str, amount: float) -> str:
    """`a` moved `amount` (0…1) towards `b`, in sRGB, as `#rrggbb`."""
    out = (
        # half up, like Math.round in the frontend's mirror
        int(int(a[i : i + 2], 16) * (1 - amount) + int(b[i : i + 2], 16) * amount + 0.5)
        for i in (1, 3, 5)
    )
    return "#" + "".join(f"{c:02x}" for c in out)


def ink_of(color: str, colors: ThemeColors) -> str:
    """`color` as text on background and surface: itself when it reads (4.5:1),
    else moved towards `text` in 5 % steps until it does. (Mirrored in
    frontend/src/styles/theme.ts `inkOf`.)"""
    for step in range(21):
        candidate = mix(color, colors.text, step / 20)
        if (
            contrast(candidate, colors.background) >= MIN_CONTRAST
            and contrast(candidate, colors.surface) >= MIN_CONTRAST
        ):
            return candidate
    return colors.text


# ----------------------------------------------------------------- validation


def invalid_theme(message: str, field: str | None = None) -> errors.ApiError:
    return errors.ApiError(400, "invalid_theme", message, field=field)


def _ratio(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def parse_colors(raw: Any) -> ThemeColors:
    """Validate the admin's colours (lower-cased first); 400 `invalid_theme`
    names the field or the pair that is not readable."""
    if not isinstance(raw, dict):
        raise invalid_theme("Ungültige Farben.", "colors")
    lowered = {k: v.lower() if isinstance(v, str) else v for k, v in raw.items()}
    try:
        colors = ThemeColors.model_validate(lowered)
    except ValidationError as exc:
        details = exc.errors()
        loc = [p for p in (details[0]["loc"] if details else ()) if isinstance(p, str)]
        name = loc[0] if loc else "colors"
        raise invalid_theme(
            f"Ungültige Farbe: {name} (erwartet #rrggbb).", f"colors.{name}"
        ) from None
    for fg, bg in CHECKED_PAIRS:
        ratio = contrast(getattr(colors, fg), getattr(colors, bg))
        if ratio < MIN_CONTRAST:
            raise invalid_theme(
                f"{LABELS[fg]} auf {LABELS[bg]} ist schlecht lesbar: Kontrast "
                f"{_ratio(ratio)}:1, nötig sind mindestens 4,5:1.",
                f"colors.{fg}/{bg}",
            )
    return colors


# --------------------------------------------------------------------- service


def css_variables(theme: PublicTheme) -> str:
    """The theme as CSS custom properties on :root (`--t-<name>`; underscores
    become dashes). Mirrored in frontend/src/styles/theme.ts `themeVariables`."""
    values = theme.colors.model_dump() | {
        "on_primary": theme.on_primary,
        "on_accent": theme.on_accent,
        "primary_ink": theme.primary_ink,
    }
    body = ";".join(f"--t-{k.replace('_', '-')}:{v}" for k, v in values.items())
    return f":root{{{body}}}\n"


class ThemeService:
    def __init__(self, db: Database, repos: Repositories, events: AdminEvents) -> None:
        self.db = db
        self.repos = repos
        self.events = events

    def _stored(self) -> tuple[dict[str, Any], str | None]:
        return self.repos.app_settings.get_entry(THEME_KEY)

    def admin_theme(self) -> AdminTheme:
        raw, at = self._stored()
        preset = raw.get("preset")
        try:
            colors = ThemeColors.model_validate(raw.get("colors"))
        except ValidationError:
            raw, at, colors = {}, None, DEFAULT_PRESET.colors
        if preset not in ("neon_nacht", "klassisch", "custom"):
            preset = DEFAULT_PRESET.id
        by = raw.get("by")
        return AdminTheme(
            preset=preset,
            colors=colors,
            on_primary=readable_on(colors.primary, colors),
            on_accent=readable_on(colors.accent, colors),
            primary_ink=ink_of(colors.primary, colors),
            rev=int(raw.get("rev") or 0),
            custom=bool(raw),
            updated_at=at if raw else None,
            by=by if isinstance(by, str) else None,
        )

    def public(self) -> PublicTheme:
        theme = self.admin_theme()
        return PublicTheme(**theme.model_dump(include=set(PublicTheme.model_fields)))

    def admin_out(self) -> AdminThemeOut:
        return AdminThemeOut(theme=self.admin_theme(), presets=list(PRESETS))

    def etag(self, theme: PublicTheme | None = None) -> str:
        data = (theme or self.public()).model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        return f'"t{digest[:20]}"'

    def css(self) -> str:
        return css_variables(self.public())

    def head_html(self) -> str:
        """The <link> every guest page carries (before the first paint)."""
        return f'<link rel="stylesheet" href="/api/theme.css?v={self.etag()[2:12]}">'

    def save(self, body: ThemeIn, *, actor: str) -> AdminThemeOut:
        if body.preset == "custom" and body.colors is None:
            raise invalid_theme("Eigene Farben brauchen alle Farben.", "colors")
        if body.colors is None:
            colors = next(p.colors for p in PRESETS if p.id == body.preset)
        else:
            colors = parse_colors(body.colors)
        with self.db.tx():
            old = self.admin_theme()
            at = now_iso()
            self.repos.app_settings.put(
                THEME_KEY,
                {
                    "preset": body.preset,
                    "colors": colors.model_dump(),
                    "rev": old.rev + 1,
                    "by": actor,
                },
                at=at,
            )
            self.repos.audit.log(actor, "settings.theme", details={"preset": body.preset}, at=at)
            self.events.theme_changed()
        return self.admin_out()

    def reset(self, *, actor: str) -> AdminThemeOut:
        """Back to the default preset (the key is removed)."""
        with self.db.tx():
            if self.repos.app_settings.delete(THEME_KEY):
                self.repos.audit.log(
                    actor, "settings.theme", details={"preset": "reset"}, at=now_iso()
                )
                self.events.theme_changed()
        return self.admin_out()
