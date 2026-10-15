"""The guest UI's and the Live Wall's colours (`/api/theme`, `/api/admin/theme`).

Stored in the settings key `x.theme`; absent = the default preset „Neon Nacht“.
The admin UI never uses it (it keeps its own look)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ThemePresetId = Literal["neon_nacht", "klassisch", "rummel", "custom"]
# the layer on top of the colours: "elegant" (calm) or "goofy" (the „Rummel“ fairground
# look: googly eyes, chasing bulbs, jelly buttons; <html data-vb-style="goofy">)
ThemeStyle = Literal["elegant", "goofy"]
THEME_COLOR_PATTERN = r"^#[0-9a-f]{6}$"
ThemeColor = Annotated[str, Field(pattern=THEME_COLOR_PATTERN)]


class ThemeColors(BaseModel):
    """Every colour as `#rrggbb` (lower case)."""

    model_config = ConfigDict(extra="forbid")

    background: ThemeColor = Field(description="Main background of every guest page.")
    surface: ThemeColor = Field(description="Raised areas: cards, sheets, the guest pass.")
    depth: ThemeColor = Field(description="Shadows, sunk areas, fields.")
    primary: ThemeColor = Field(description="Main actions, the shutter ring, the glow.")
    secondary: ThemeColor = Field(description="The event name (wordmark), soft accents.")
    tertiary: ThemeColor = Field(description="Cool detail: counters' units, quiet icons.")
    accent: ThemeColor = Field(description="Beat accents: badges, live marks, transitions.")
    highlight: ThemeColor = Field(description="Small specular highlights.")
    hit: ThemeColor = Field(description="Brief flashes only (a photo was taken).")
    text: ThemeColor = Field(description="Readable text (≥ 4.5:1 on background and surface).")
    text_muted: ThemeColor = Field(
        description="Secondary text (≥ 4.5:1 on background and surface)."
    )


class ThemePreset(BaseModel):
    id: Literal["neon_nacht", "klassisch", "rummel"]
    label: str
    colors: ThemeColors
    style: ThemeStyle = Field(description="The style the preset comes with.")


class PublicTheme(BaseModel):
    """What every guest page and the wall read (no auth)."""

    preset: ThemePresetId
    colors: ThemeColors
    on_primary: ThemeColor = Field(description="Text on a `primary` fill (best contrast).")
    on_accent: ThemeColor = Field(description="Text on an `accent` fill (best contrast).")
    primary_ink: ThemeColor = Field(
        description="`primary` as text: itself, or lightened towards `text` until it "
        "reads on background and surface (4.5:1)."
    )
    style: ThemeStyle = Field(
        "elegant",
        description="The look's layer on guest pages and the wall: `elegant` or `goofy` "
        "(<html data-vb-style>).",
    )
    rev: int = Field(description="Counts saves; 0 = never saved (the default).")


class AdminTheme(PublicTheme):
    custom: bool = Field(description="The host saved a theme (false: the default applies).")
    updated_at: str | None
    by: str | None


class AdminThemeOut(BaseModel):
    theme: AdminTheme
    presets: list[ThemePreset]


class ThemeIn(BaseModel):
    """Save a theme. Without `colors` the preset's colours apply."""

    preset: ThemePresetId
    colors: dict[str, str] | None = Field(
        None, description="All colours of ThemeColors as #rrggbb; null: the preset's."
    )
    style: ThemeStyle | None = Field(
        None, description="The layer; null: the preset's (`custom`: elegant)."
    )
