"""Printable QR codes with the party token baked into the URLs.

    python -m virtubooth.tools.qr --base-url https://party.example.com

One code for the home page (`<base>/?t=<token>`) and one per extension
(`<base>/x/<id>/?t=<token>`), each as SVG and PNG, plus `qr-sheet.html`: an
A4 page per code with emoji, title, tagline, the big code and a short
instruction, ready to print. Error correction level H (30 %), so a beer stain
or a crease doesn't kill a code. The token is only inside the codes, never
printed as text.
"""

from __future__ import annotations

import argparse
import html
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import segno

from ..config import TOKEN_RE, ConfigError
from ..extension import Extension, discover_extensions
from ._common import (
    ToolError,
    add_data_dir_arg,
    env_list,
    exports_dir,
    resolve_data_dir,
    run,
    split_list,
)

PROG = "python -m virtubooth.tools.qr"
ERROR_LEVEL = "h"
INSTRUCTION = "Handy-Kamera drauf halten und los!"
HOME_TAGLINE = "Alle Aktionen auf einen Blick"
SHEET_NAME = "qr-sheet.html"
# PNGs get at least this many pixels per side (about 14 cm at 300 dpi)
PNG_MIN_PX = 1600


@dataclass(frozen=True)
class Card:
    key: str  # file name part: qr-<key>.svg
    title: str
    emoji: str
    tagline: str
    url: str


def normalize_base_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ToolError(f"base URL {raw!r} must look like https://party.example.com")
    if parts.query or parts.fragment:
        raise ToolError("base URL must not contain '?' or '#'")
    return url


def entry_url(base_url: str, token: str, path: str = "/") -> str:
    """The URL a code points to; the app moves `t` into a cookie and redirects."""
    return f"{base_url}{path}?{urlencode({'t': token})}"


def home_url(base_url: str, token: str) -> str:
    return entry_url(base_url, token, "/")


def extension_url(base_url: str, token: str, ext_id: str) -> str:
    return entry_url(base_url, token, f"/x/{quote(ext_id, safe='')}/")


def build_cards(
    base_url: str,
    token: str,
    extensions: Sequence[Extension],
    *,
    party_name: str = "Party",
    home: bool = True,
) -> list[Card]:
    cards = []
    if home:
        cards.append(Card("home", party_name, "🎉", HOME_TAGLINE, home_url(base_url, token)))
    for ext in extensions:
        key = ext.id if ext.id != "home" else "x-home"
        cards.append(
            Card(key, ext.title, ext.emoji, ext.tagline, extension_url(base_url, token, ext.id))
        )
    return cards


def make_qr(url: str) -> segno.QRCode:
    return segno.make_qr(url, error=ERROR_LEVEL, boost_error=False)


def write_codes(cards: Sequence[Card], out_dir: Path) -> list[Path]:
    written = []
    for card in cards:
        qr = make_qr(card.url)
        svg, png = out_dir / f"qr-{card.key}.svg", out_dir / f"qr-{card.key}.png"
        qr.save(svg, kind="svg", scale=10, border=4, dark="#000", light="#fff")
        modules = qr.symbol_size(scale=1, border=4)[0]
        qr.save(png, kind="png", scale=-(-PNG_MIN_PX // modules), border=4)
        written += [svg, png]
    return written


# ----------------------------------------------------------------- sheet

SHEET_CSS = """
@page { size: A4 portrait; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial,
    "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif;
  color: #1d1230; background: #e7e3ee;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.hint {
  max-width: 210mm; margin: 16px auto; padding: 12px 18px; border-radius: 12px;
  background: #fff; font-size: 15px; line-height: 1.5;
}
.card {
  position: relative; overflow: hidden; width: 210mm; height: 297mm; margin: 0 auto 24px;
  padding: 20mm 18mm; background: #fff; text-align: center;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  box-shadow: 0 6px 28px rgba(29, 18, 48, .18);
  break-inside: avoid; page-break-inside: avoid;
  break-after: page; page-break-after: always;
}
.card:last-child { break-after: auto; page-break-after: auto; }
.card::before, .card::after {
  content: ""; position: absolute; left: 0; right: 0; height: 8mm;
  background: linear-gradient(90deg, #ff2d95, #ff7a18, #ffd60a);
}
.card::before { top: 0; }
.card::after { bottom: 0; }
.party {
  margin: 0 0 6mm; font-size: 13pt; font-weight: 700; letter-spacing: .2em;
  text-transform: uppercase; color: #7a6a8e;
}
.emoji { margin: 0 0 3mm; font-size: 54pt; line-height: 1.1; }
h1 { margin: 0 0 3mm; font-size: 40pt; line-height: 1.1; font-weight: 800; }
.tagline { max-width: 165mm; margin: 0 0 9mm; font-size: 17pt; line-height: 1.3; color: #4a3b5f; }
.qr { width: 135mm; height: 135mm; }
.qr svg { display: block; width: 100%; height: 100%; }
.cta { margin: 9mm 0 0; font-size: 24pt; font-weight: 800; }
@media print {
  body { background: #fff; }
  .hint { display: none; }
  .card { margin: 0; box-shadow: none; }
}
"""


def render_sheet(cards: Sequence[Card], party_name: str) -> str:
    e = html.escape
    pages = []
    for card in cards:
        svg = make_qr(card.url).svg_inline(
            scale=1, border=4, dark="#000", light="#fff", omitsize=True
        )
        # the home card's title already is the party name
        label = f'  <p class="party">{e(party_name)}</p>\n' if card.title != party_name else ""
        pages.append(
            f'<section class="card" id="card-{e(card.key)}">\n'
            f"{label}"
            f'  <div class="emoji">{e(card.emoji)}</div>\n'
            f"  <h1>{e(card.title)}</h1>\n"
            f'  <p class="tagline">{e(card.tagline)}</p>\n'
            f'  <div class="qr" role="img" aria-label="QR-Code: {e(card.title)}">{svg}</div>\n'
            f'  <p class="cta">{e(INSTRUCTION)}</p>\n'
            "</section>"
        )
    n = len(cards)
    return (
        '<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>QR-Codes · {e(party_name)}</title>\n<style>{SHEET_CSS}</style>\n</head>\n<body>\n"
        f'<div class="hint"><strong>{n} Seite{"n" if n != 1 else ""} A4.</strong> '
        "Drucken mit Strg+P (⌘P): Ränder „Keine“, Hintergrundgrafiken an. "
        "Die Codes enthalten den Party-Zugang: nicht öffentlich posten.</div>\n"
        + "\n".join(pages)
        + "\n</body>\n</html>\n"
    )


# ------------------------------------------------------------------- CLI


def load_extensions(names: list[str] | None) -> list[Extension]:
    """Named extensions in that order; by default every extension on the home page."""
    try:
        exts = discover_extensions(names)
    except ConfigError as exc:
        raise ToolError(str(exc)) from exc
    return exts if names is not None else [e for e in exts if e.show_on_home]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Generate the party QR codes (token baked in) as SVG + PNG and a "
        "printable A4 sheet (qr-sheet.html, one page per code).",
        epilog="example:\n"
        f"  {PROG} --base-url https://party.example.com --extensions beer,booth\n\n"
        "Codes: <base>/?t=<token> (home page) and <base>/x/<extension>/?t=<token>.\n"
        "Rotating VB_PARTY_TOKEN invalidates printed codes: print them after the final token.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--base-url",
        metavar="URL",
        help="public URL guests open, e.g. https://party.example.com "
        "(default: $VB_PUBLIC_BASE_URL)",
    )
    p.add_argument("--token", help="party token baked into the codes (default: $VB_PARTY_TOKEN)")
    p.add_argument(
        "--extensions",
        metavar="LIST",
        help="comma-separated extension ids (default: $VB_EXTENSIONS, else every "
        "extension shown on the home page); the sheet follows the extensions' order",
    )
    p.add_argument(
        "--party-name",
        metavar="NAME",
        help="heading on the sheet and title of the home card (default: $VB_PARTY_NAME or 'Party')",
    )
    p.add_argument("--no-home", action="store_true", help="leave out the home page code")
    p.add_argument(
        "--out", metavar="DIR", help="output directory (default: <data-dir>/exports/qr/)"
    )
    add_data_dir_arg(p)
    return p


def _main(args: argparse.Namespace) -> int:
    base_raw = args.base_url or os.environ.get("VB_PUBLIC_BASE_URL", "").strip()
    if not base_raw:
        raise ToolError("no base URL: pass --base-url or set VB_PUBLIC_BASE_URL")
    base_url = normalize_base_url(base_raw)
    token = (args.token or os.environ.get("VB_PARTY_TOKEN", "")).strip()
    if not token:
        raise ToolError("no party token: pass --token or set VB_PARTY_TOKEN")
    if not TOKEN_RE.match(token):
        raise ToolError("the party token must be 16-128 chars of A-Z a-z 0-9 _ -")
    names = split_list(args.extensions) if args.extensions else env_list("VB_EXTENSIONS")
    extensions = load_extensions(names)
    party_name = (args.party_name or os.environ.get("VB_PARTY_NAME", "")).strip() or "Party"
    out_dir = (
        Path(args.out).expanduser().resolve()
        if args.out
        else exports_dir(resolve_data_dir(args.data_dir)) / "qr"
    )

    cards = build_cards(base_url, token, extensions, party_name=party_name, home=not args.no_home)
    if not cards:
        raise ToolError("nothing to do: no extensions and --no-home")
    if not extensions:
        print("warning: no extensions found, only the home page code is generated")
    host = urlsplit(base_url).hostname or ""
    if base_url.startswith("http://") and host not in ("localhost", "127.0.0.1", "::1"):
        print("warning: http:// URL; phones only allow the camera over https")

    out_dir.mkdir(parents=True, exist_ok=True)
    write_codes(cards, out_dir)
    sheet = out_dir / SHEET_NAME
    sheet.write_text(render_sheet(cards, party_name), encoding="utf-8")

    print(f"QR codes in {out_dir}:")
    for card in cards:
        shown = card.url.replace(token, "<token>")
        print(f"  qr-{card.key}.svg/.png  {card.emoji} {card.title}  {shown}")
    print(f"Printable sheet: {sheet} ({len(cards)} A4 pages; open it and print)")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_main, build_parser(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
