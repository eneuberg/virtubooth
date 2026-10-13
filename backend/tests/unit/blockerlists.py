"""Content-blocker checks without third-party code (used by test_core_blockers.py).

- `app_requests()`: every URL the app serves or requests (routes, static files,
  QR entry URLs, media URLs, URLs written in the JS), as a guest's browser
  would fetch them from a real first-party host.
- `ui_elements()`: the DOM the pages build: the HTML files as trees, the
  `h('tag', {attrs}, ...children)` calls in the JS as trees, plus every class
  name written in the CSS/JS as a stand-alone element.
- `NetworkRules` / `CosmeticRules`: a matcher for the subset of the
  EasyList/uBlock Origin/AdGuard filter syntax that can hit a first-party site:
  generic network rules (with removeparam and response-modifying options) and
  generic element-hiding selectors (CSS incl. :not/:is/:has and :has-text).

Cross-checked against Brave's adblock-rust and Chromium's CSS engine; see
docs/ARCHITECTURE.md ("Content blockers").
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

HOST = "party.fentreactor.de"
BASE = f"https://{HOST}"

# ---------------------------------------------------------------- requests


@dataclass(frozen=True)
class Request:
    url: str
    type: str  # script | stylesheet | image | xmlhttprequest | document | other
    method: str = "GET"
    source: str = BASE + "/"


ASSET_TYPES = {
    ".js": "script",
    ".mjs": "script",
    ".css": "stylesheet",
    ".html": "document",
    ".json": "xmlhttprequest",
    ".svg": "image",
    ".png": "image",
    ".jpg": "image",
    ".webmanifest": "other",
    ".woff2": "font",
}
JS_URL = re.compile(
    r"""['"`](/(?:api|media|admin|assets|x)/[^'"`\s]*|\./[\w.-]+\.(?:js|json|css))['"`]"""
)


def _routes(routes: Iterable, prefix: str = "") -> Iterator[tuple[str, set[str]]]:
    """(path, methods) of every route, through FastAPI's lazily included routers."""
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _routes(route.original_router.routes, prefix + route.include_context.prefix)
        elif hasattr(route, "methods") and hasattr(route, "path"):
            yield prefix + route.path, set(route.methods or {"GET"})


def served_files(root: Path) -> Iterator[tuple[str, Path]]:
    """(URL path, file) of everything the web module serves from a frontend
    build: `assets/**` and the public root files. The HTML entries are served
    under their routes (see app_requests); .br/.gz siblings under the original
    name; dotfiles (e.g. .vite/manifest.json) never."""
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root).as_posix()
        if not f.is_file() or any(part.startswith(".") for part in rel.split("/")):
            continue
        if f.suffix in (".br", ".gz") or rel in ("index.html", "admin.html", "gate.html"):
            continue
        if rel.startswith("assets/") or "/" not in rel:
            yield "/" + rel, f


def app_requests(app, token: str, web_dirs: Sequence[Path] = ()) -> list[Request]:
    """Every URL the app serves or requests. `web_dirs`: frontend builds whose
    files count as served too (the app's own VB_WEB_DIR always does)."""
    core = app.state.core
    exts = list(core.extensions.values())
    # fixed, same shape as the real ones (token_urlsafe(12), sha256 hex); 300k random
    # ids were checked against all lists once without a single hit
    photo = "kQ3x_vN8aLp2Rt0Y"
    fp_hash = "3f9a" * 16
    cursor = f"{core.bus.epoch}-42"
    out: list[Request] = []

    def add(path: str, typ: str, method: str = "GET", source: str = "/") -> None:
        out.append(Request(BASE + path, typ, method, BASE + source))

    # the built frontend: hashed assets and public root files (boot-check.js, icon.svg)
    roots = [core.web.root] if core.web.root is not None else []
    js_files: list[Path] = []
    for root in dict.fromkeys([*roots, *web_dirs]):
        for url, f in served_files(root):
            add(url, ASSET_TYPES.get(f.suffix, "other"), source="/")
            if f.suffix in (".js", ".mjs"):
                js_files.append(f)

    # pages and the QR codes' entry URLs
    admin_pages = ["/admin/live", "/admin/manage", "/admin/user"]
    tabs = ("fotos", "gaeste", "instagram", "sperren", "protokoll", "export")
    for path in [
        "/",
        "/healthz",
        "/admin",
        "/admin/login",
        "/admin/login?next=%2Fadmin%2Flive",
        *admin_pages,
        "/admin/user?id=17",
        *(f"/admin/manage?tab={t}" for t in tabs),
    ]:
        add(path, "document")
    add(f"/?t={token}", "document")
    # deep links to a photo (PLAN §1: `?photo=` on the admin screens)
    for path in (
        f"/admin/live?photo={photo}",
        f"/admin/manage?tab=fotos&photo={photo}",
        f"/admin/user?id=17&photo={photo}",
    ):
        add(path, "document")
    for ext in exts:
        for path in (
            f"/x/{ext.id}",
            f"/x/{ext.id}/",
            f"/x/{ext.id}/?t={token}",
            f"/x/{ext.id}/?debug=1",
        ):
            add(path, "document")

    # photos: <img> on the result/admin screens, ?download=1 links
    for typ in ("image", "other"):
        add(f"/media/{photo}", typ, source="/admin/live")
        add(f"/media/{photo}?thumb=1", typ, source="/admin/live")
    add(f"/media/{photo}?download=1", "document", source="/admin/live")

    # API: every route, with the query strings the admin UI sends
    for path, methods in _routes(app.routes):
        if not path.startswith("/api/"):
            continue
        paths = [path.replace("{ext_id}", e.id) for e in exts] if "{ext_id}" in path else [path]
        for p in paths:
            p = (
                p.replace("{public_id}", photo)
                .replace("{photo_id}", photo)
                .replace("{user_id}", "17")
                .replace("{fp_hash}", fp_hash)
            )
            for method in sorted(methods - {"HEAD"}):
                add(p, "xmlhttprequest", method)
    add("/api/admin/events", "other", source="/admin/live")  # EventSource
    add(f"/api/admin/events?since={cursor}", "other", source="/admin/live")
    for query in (
        "limit=60",
        f"limit=60&before={photo}",
        f"limit=200&after={photo}&extension=beer&hidden=all&user_id=17",
    ):
        add(f"/api/admin/photos?{query}", "xmlhttprequest", source="/admin/manage")
    add("/api/admin/users?search=giraffe&banned=true&limit=100&offset=0", "xmlhttprequest")
    add("/api/admin/users?paused=true&limit=100&offset=100", "xmlhttprequest")
    add("/api/admin/audit?limit=100&before=5", "xmlhttprequest")

    # whatever the built JS fetches or imports by literal URL
    for f in js_files:
        for m in JS_URL.finditer(f.read_text(encoding="utf-8", errors="replace")):
            u = re.sub(r"\$\{[^}]*\}", "x", m.group(1))
            if u.startswith("./"):
                u = "/assets/" + u[2:]
            add(u, "script" if u.endswith(".js") else "xmlhttprequest")

    unique: dict[tuple[str, str, str], Request] = {}
    for r in out:
        unique.setdefault((r.url, r.type, r.method), r)
    return list(unique.values())


# ---------------------------------------------------------- network rules

TYPE_ALIASES = {
    "xhr": "xmlhttprequest",
    "css": "stylesheet",
    "doc": "document",
    "frame": "subdocument",
    "beacon": "ping",
    "object-subrequest": "object",
    "1p": "first-party",
    "3p": "third-party",
}
TYPES = {
    "script",
    "image",
    "stylesheet",
    "xmlhttprequest",
    "subdocument",
    "document",
    "media",
    "font",
    "object",
    "ping",
    "websocket",
    "other",
    "webrtc",
    "popup",
    "popunder",
    "webtransport",
}
DEFAULT_TYPES = TYPES - {"document", "popup", "popunder"}
# options that rewrite a request or response instead of blocking it: fail when they apply
MODIFIERS = {
    "csp",
    "permissions",
    "replace",
    "urltransform",
    "uritransform",
    "urlskip",
    "removeheader",
    "responseheader",
    "jsonprune",
    "xmlprune",
    "hls",
}
# rules with these never block or rewrite one of our requests by themselves
NON_BLOCKING = {
    "cookie",
    "stealth",
    "elemhide",
    "ehide",
    "generichide",
    "ghide",
    "specifichide",
    "shide",
    "genericblock",
    "redirect-rule",
    "content",
    "jsinject",
    "urlblock",
    "extension",
    "network",
    "inline-script",
    "inline-font",
    "referrerpolicy",
}
# options that don't change whether a blocking rule applies (redirect= still blocks our file)
IGNORED = {"_", "reason", "empty", "mp4", "rewrite", "redirect", "noop"}
SEPARATOR = r"(?:[^\w.%-]|$)"


@dataclass
class NetworkRule:
    text: str
    source: str
    exception: bool
    pattern: str
    regex: re.Pattern[str]
    types: set[str]
    domains: tuple[set[str], set[str]] = (set(), set())
    to: tuple[set[str], set[str]] = (set(), set())
    methods: set[str] = field(default_factory=set)
    action: str = "block"  # block | removeparam | <modifier name>
    value: str = ""
    important: bool = False
    first_party_only: bool = False

    def on_site(self, host: str) -> bool:
        """Could apply to pages and requests of `host` (domain=/to= allow it)."""
        return _domain_ok(host, *self.domains) and _domain_ok(host, *self.to)

    def applies(self, req: Request) -> bool:
        host = urlsplit(req.url).hostname or ""
        page = urlsplit(req.source).hostname or ""
        if req.type not in self.types:
            return False
        if self.first_party_only and _site(host) != _site(page):
            return False
        if self.methods and req.method.lower() not in self.methods:
            return False
        if not _domain_ok(page, *self.domains) or not _domain_ok(host, *self.to):
            return False
        return bool(self.regex.search(req.url))

    def removes(self, name: str) -> bool:
        v = self.value
        neg = v.startswith("~")
        v = v[1:] if neg else v
        if v == "":
            hit = True
        elif len(v) > 2 and v.startswith("/") and v.rstrip("i").endswith("/"):
            try:
                rx = re.compile(v[1 : v.rstrip("i").rindex("/")], re.I if v.endswith("i") else 0)
            except re.error:
                return False
            hit = bool(rx.search(name) or rx.search(f"{name}="))
        else:
            hit = v == name
        return hit != neg


def _host_in(host: str, entry: str) -> bool:
    if entry.startswith("/") and entry.endswith("/") and len(entry) > 2:
        try:
            return re.search(entry[1:-1], host) is not None
        except re.error:
            return False
    if entry.endswith(".*"):  # entity: example.* matches example.de, sub.example.co.uk
        base = entry[:-2]
        labels = host.split(".")
        return any(".".join(labels[i:]).startswith(base + ".") for i in range(len(labels)))
    return host == entry or host.endswith("." + entry)


def _site(host: str) -> str:
    """Rough registrable domain (last two labels), enough to tell 1p from 3p here."""
    return ".".join(host.split(".")[-2:])


def _domain_ok(host: str, pos: set[str], neg: set[str]) -> bool:
    if any(_host_in(host, d) for d in neg):
        return False
    return not pos or any(_host_in(host, d) for d in pos)


def _split_options(line: str) -> tuple[str, str]:
    i = line.rfind("$")
    if i <= 0 and not line.startswith("$"):
        return line, ""
    pattern, opts = line[:i], line[i + 1 :]
    if pattern.startswith("/") and not pattern.endswith("/") and "/" in opts:
        return line, ""  # the $ belongs to a regex
    if not re.match(r"^~?[\w-]+(=|,|$)", opts):
        return line, ""
    return pattern, opts


def _split_commas(opts: str) -> list[str]:
    """Options split on commas, except inside /regex/ values."""
    parts, cur, in_rx = [], "", False
    for i, ch in enumerate(opts):
        if ch == "/" and (cur.endswith("=") or in_rx) and (i == 0 or opts[i - 1] != "\\"):
            in_rx = not in_rx
        if ch == "," and not in_rx:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def pattern_regex(pattern: str, match_case: bool) -> re.Pattern[str] | None:
    flags = 0 if match_case else re.I
    if len(pattern) > 2 and pattern.startswith("/") and pattern.endswith("/"):
        try:
            return re.compile(pattern[1:-1], flags)
        except re.error:
            return None
    rx = ""
    if pattern.startswith("||"):
        rx, pattern = r"^[a-z][a-z0-9+.-]*://(?:[^/?#]*\.)?", pattern[2:]
    elif pattern.startswith("|"):
        rx, pattern = "^", pattern[1:]
    end = pattern.endswith("|")
    if end:
        pattern = pattern[:-1]
    for ch in pattern:
        rx += ".*" if ch == "*" else SEPARATOR if ch == "^" else re.escape(ch)
    if end:
        rx += "$"
    try:
        return re.compile(rx, flags)
    except re.error:
        return None


def _literal(pattern: str) -> str:
    """Longest literal run of a plain pattern (prefilter)."""
    if pattern.startswith("/") and pattern.endswith("/"):
        return ""
    runs = re.split(r"[*^|]", pattern)
    return max(runs, key=len).lower() if runs else ""


def _hosts_line(line: str) -> str | None:
    m = re.match(r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1?)\s+([a-z0-9._-]+)\s*(?:#.*)?$", line, re.I)
    if m and m.group(1) not in ("localhost", "0.0.0.0", "local"):
        return f"||{m.group(1)}^"
    return None


COSMETIC_MARKERS = ("##", "#@#", "#?#", "#$#", "#%#", "#@$#", "#@%#", "#@?#", "$$", "$@$", "#$?#")


class NetworkRules:
    """Rules of one or more lists that could apply to requests in `corpus`."""

    def __init__(self, corpus: Iterable[str]) -> None:
        self.corpus = " ".join(corpus).lower()
        self.rules: list[NetworkRule] = []
        self.badfilters: set[str] = set()
        self.skipped = 0

    def add_list(self, text: str, source: str) -> None:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line[0] in "![" or any(m in line for m in COSMETIC_MARKERS):
                continue
            hosts = _hosts_line(line)
            if hosts:
                line = hosts
            elif line[0] == "#" or (line[0] in "0123456789:" and " " in line):
                continue  # hosts-file comments and entries we don't care about
            rule = self._parse(line, source)
            if rule is not None:
                self.rules.append(rule)
        if self.badfilters:
            self.rules = [r for r in self.rules if r.text not in self.badfilters]

    def _parse(self, line: str, source: str) -> NetworkRule | None:
        exception = line.startswith("@@")
        body = line[2:] if exception else line
        pattern, opts = _split_options(body)
        if pattern in ("", "*"):
            pattern = ""
        lit = _literal(pattern)
        if pattern.startswith("||"):
            host = re.match(r"[a-z0-9.*_-]*", pattern[2:], re.I).group(0).lower()  # type: ignore[union-attr]
            if host and "*" not in host and host not in self.corpus:
                return None
        if len(lit) >= 3 and lit not in self.corpus:
            return None
        types: set[str] = set()
        neg_types: set[str] = set()
        rule = NetworkRule(line, source, exception, pattern, re.compile(""), set())
        match_case = False
        for opt in _split_commas(opts) if opts else []:
            name, _, value = opt.partition("=")
            neg = name.startswith("~")
            name = TYPE_ALIASES.get(name.lstrip("~"), name.lstrip("~"))
            if name in TYPES:
                (neg_types if neg else types).add(name)
            elif name == "all":
                types |= TYPES
            elif name == "third-party":
                if not neg:
                    return None  # never applies to our own (first-party) requests
                rule.first_party_only = True
            elif name in ("first-party", "strict1p"):
                if neg:
                    return None
                rule.first_party_only = True
            elif name == "strict3p":
                return None
            elif name in ("domain", "from", "to", "denyallow"):
                pos = {d for d in value.split("|") if d and not d.startswith("~")}
                negd = {d[1:] for d in value.split("|") if d.startswith("~")}
                if name == "denyallow":
                    pos, negd = set(), pos
                if name in ("to", "denyallow"):
                    rule.to = (rule.to[0] | pos, rule.to[1] | negd)
                else:
                    rule.domains = (rule.domains[0] | pos, rule.domains[1] | negd)
            elif name == "method":
                rule.methods = {m.lower() for m in value.split("|") if not m.startswith("~")}
            elif name in ("removeparam", "queryprune"):
                rule.action, rule.value = "removeparam", value
            elif name in MODIFIERS:
                rule.action, rule.value = name, value
            elif name in NON_BLOCKING:
                return None
            elif name == "badfilter":
                self.badfilters.add(line.replace("$badfilter", "").replace(",badfilter", ""))
                return None
            elif name == "match-case":
                match_case = True
            elif name == "important":
                rule.important = True
            elif name in IGNORED:
                pass
            else:
                self.skipped += 1  # ipaddress=, header=, app=, unknown: can't evaluate
                return None
        if types:
            rule.types = types - neg_types
        else:
            rule.types = DEFAULT_TYPES - neg_types
            if re.fullmatch(r"\|\|[a-z0-9.-]+\^?", pattern, re.I) or rule.action != "block":
                rule.types = rule.types | {"document"}  # strict blocking, or doc modifiers
        if rule.action in ("urlskip", "uritransform") and not types:
            rule.types = rule.types | {"document"}
        if rule.action in ("csp", "permissions"):
            rule.types = {"document", "subdocument"}  # response headers of pages only
        rx = pattern_regex(pattern, match_case)
        if rx is None:
            return None
        rule.regex = rx
        return rule

    def check(self, req: Request) -> list[NetworkRule]:
        """Rules that block or modify `req` (empty: the request survives)."""
        hits = [r for r in self.rules if not r.exception and r.applies(req)]
        if not hits:
            return []
        excs = [r for r in self.rules if r.exception and r.applies(req)]
        out = []
        params = [k for k, _ in parse_qsl(urlsplit(req.url).query, keep_blank_values=True)]
        for r in hits:
            same = [
                e
                for e in excs
                if e.action == r.action and (r.action != "removeparam" or e.value in ("", r.value))
            ]
            if same and not r.important:
                continue
            if r.action == "removeparam" and not any(r.removes(p) for p in params):
                continue
            if r.action == "permissions" and "camera" not in r.value:
                continue  # only the camera matters to us (topics/FLEDGE/attribution off is fine)
            out.append(r)
        return out


# --------------------------------------------------------- cosmetic rules


@dataclass
class CosmeticRule:
    text: str
    source: str
    selector: str


ACTION_SUFFIX = re.compile(r":(?:style|remove|remove-attr|remove-class)\(.*\)$")


class CosmeticRules:
    """Generic element-hiding rules: they apply on every site, including ours."""

    def __init__(self) -> None:
        self.rules: dict[str, list[CosmeticRule]] = {}
        self.exceptions: set[str] = set()

    def add_list(self, text: str, source: str) -> None:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line[0] in "![":
                continue
            for sep in ("#@?#", "#@$#", "#@#", "#?#", "#$#", "##"):
                i = line.find(sep)
                if i < 0:
                    continue
                domains = line[:i]
                if any(d not in ("", "*") and not d.startswith("~") for d in domains.split(",")):
                    break  # site-specific
                sel = line[i + len(sep) :]
                if sel.startswith(("+js(", "^")):
                    break  # scriptlets (checked elsewhere), HTML filters
                if sep.endswith("$#"):
                    sel = sel.split("{", 1)[0].strip()  # CSS injection: selector { style }
                sel = ACTION_SUFFIX.sub("", sel)
                if "@" in sep:
                    self.exceptions.add(sel)
                else:
                    self.rules.setdefault(sel, []).append(CosmeticRule(line, source, sel))
                break

    def check(self, elements: list[El]) -> list[tuple[CosmeticRule, El]]:
        index = _Index(elements)
        hits = []
        for sel, rules in self.rules.items():
            if sel in self.exceptions:
                continue
            try:
                parsed = parse_selector_list(sel)
            except SelectorError:
                continue
            for complex_sel in parsed:
                for el in index.candidates(complex_sel[-1][1]):
                    if match_complex(complex_sel, el):
                        hits.append((rules[0], el))
                        break
        return hits


# ----------------------------------------------------- elements (the DOM)


@dataclass(eq=False)
class El:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[El] = field(default_factory=list)
    parent: El | None = None
    text: str = ""
    origin: str = ""

    def append(self, child: El) -> None:
        child.parent = self
        self.children.append(child)

    @property
    def classes(self) -> list[str]:
        return self.attrs.get("class", "").split()

    def all_text(self) -> str:
        return self.text + " ".join(c.all_text() for c in self.children)

    def describe(self) -> str:
        s = self.tag + (f"#{self.attrs['id']}" if self.attrs.get("id") else "")
        s += "".join(f".{c}" for c in self.classes)
        s += "".join(
            f'[{k}="{v}"]'
            for k, v in self.attrs.items()
            if k.startswith(("data-", "role", "aria-"))
        )
        return f"{s} ({self.origin})"

    def walk(self) -> Iterator[El]:
        yield self
        for c in self.children:
            yield from c.walk()


def new_document(origin: str) -> tuple[El, El]:
    """An empty <html><body> to hang elements on; returns (html, body)."""
    html = El("html", origin=origin)
    body = El("body", origin=origin)
    html.append(body)
    return html, body


class _TreeBuilder(HTMLParser):
    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, origin: str) -> None:
        super().__init__()
        self.root = El("#document", origin=origin)
        self.stack = [self.root]
        self.origin = origin

    def handle_starttag(self, tag, attrs):  # type: ignore[no-untyped-def]
        el = El(tag, {k: v or "" for k, v in attrs}, origin=self.origin)
        self.stack[-1].append(el)
        if tag not in self.VOID:
            self.stack.append(el)

    def handle_endtag(self, tag):  # type: ignore[no-untyped-def]
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):  # type: ignore[no-untyped-def]
        self.stack[-1].text += data


def html_tree(text: str, origin: str) -> El:
    tb = _TreeBuilder(origin)
    tb.feed(text)
    html = next((c for c in tb.root.children if c.tag == "html"), tb.root)
    html.parent = None
    return html


# --- JS: h('tag', {attrs}, ...children) calls as trees (a tolerant scanner, not a JS parser)


def _skip_string(src: str, i: int) -> int:
    q = src[i]
    i += 1
    while i < len(src):
        ch = src[i]
        if ch == "\\":
            i += 2
            continue
        if q == "`" and src.startswith("${", i):
            i = _match_close(src, i + 1) + 1
            continue
        if ch == q:
            return i + 1
        i += 1
    return i


def _match_close(src: str, i: int) -> int:
    """Index of the bracket closing src[i] (one of ([{)."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [pairs[src[i]]]
    i += 1
    while i < len(src) and stack:
        ch = src[i]
        if ch in "'\"`":
            i = _skip_string(src, i)
            continue
        if src.startswith("//", i):
            i = src.find("\n", i) if src.find("\n", i) >= 0 else len(src)
            continue
        if src.startswith("/*", i):
            i = src.find("*/", i) + 2 if src.find("*/", i) >= 0 else len(src)
            continue
        if ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        i += 1
    return i - 1


def _arg_spans(src: str, start: int, end: int) -> list[tuple[int, int]]:
    """Top-level comma-separated spans of src[start:end] (absolute indices)."""
    spans, depth, s, i = [], 0, start, start
    while i < end:
        ch = src[i]
        if ch in "'\"`":
            i = _skip_string(src, i)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            spans.append((s, i))
            s = i + 1
        i += 1
    spans.append((s, end))
    out = []
    for a, b in spans:
        while a < b and src[a].isspace():
            a += 1
        while b > a and src[b - 1].isspace():
            b -= 1
        if a < b:
            out.append((a, b))
    return out


def _js_literal(src: str, hole: str = "x") -> str | None:
    """Value of a string/template literal; ${...} becomes `hole`."""
    src = src.strip()
    if len(src) < 2 or src[0] not in "'\"`" or _skip_string(src, 0) != len(src):
        return None
    body = src[1:-1]
    if src[0] != "`":
        return body
    out, i = "", 0
    while i < len(body):
        if body.startswith("${", i):
            j = _match_close(body, i + 1)
            out += hole + " ".join(
                m.group(1) for m in re.finditer(r"""['"]([\w -]*)['"]""", body[i + 2 : j])
            )
            i = j + 1
        else:
            out += body[i]
            i += 1
    return out


H_CALL = re.compile(r"(?<![\w$.])h\(")
ASSIGN = re.compile(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*h\($")


class _JsTrees:
    """Elements built with h('tag', {attrs}, ...children), nested as the calls
    nest; identifiers passed as children resolve to the nearest earlier
    `const name = h(...)`. A tolerant scanner, not a JS parser."""

    def __init__(self, src: str, origin: str) -> None:
        self.src, self.origin = src, origin
        self.defs: list[tuple[int, str, El]] = []

    def calls(self, start: int, end: int) -> list[El]:
        out, pos = [], start
        for m in H_CALL.finditer(self.src, start, end):
            if m.start() < pos:
                continue
            el, close = self.parse(m.end() - 1)
            pos = close + 1
            if el is None:
                continue
            a = ASSIGN.search(self.src, max(0, m.start() - 80), m.end())
            if a:
                self.defs.append((m.start(), a.group(1), el))
            out.append(el)
        return out

    def parse(self, paren: int) -> tuple[El | None, int]:
        src = self.src
        close = _match_close(src, paren)
        spans = _arg_spans(src, paren + 1, close)
        tag = _js_literal(src[spans[0][0] : spans[0][1]]) if spans else None
        if not tag or not re.fullmatch(r"[a-zA-Z][\w-]*", tag):
            return None, close
        el = El(tag.lower(), origin=self.origin)
        if len(spans) > 1 and src[spans[1][0]] == "{":
            for key, value in _object_pairs(src, spans[1][0] + 1, spans[1][1] - 1):
                key = key.lower()
                if key == "class":
                    lit = _js_literal(value, hole=" ")
                    if lit is None:  # e.g. `a ${b}`.trim(), cond ? 'x' : 'y'
                        lit = " ".join(
                            _js_literal(m.group(0), hole=" ") or ""
                            for m in re.finditer(r"""'[^']*'|"[^"]*"|`[^`]*`""", value)
                        )
                    el.attrs["class"] = " ".join(lit.split())
                elif key == "dataset" or key.startswith("on"):
                    continue
                else:
                    lit = _js_literal(value)
                    if lit is not None:
                        el.attrs[key] = lit
                    elif value == "true":
                        el.attrs[key] = ""
        for a, b in spans[2:]:
            arg = src[a:b]
            lit = _js_literal(arg)
            if lit is not None:
                el.text += lit
            elif re.fullmatch(r"[A-Za-z_$][\w$]*", arg):
                prior = [d for d in self.defs if d[0] < a and d[1] == arg]
                if prior and prior[-1][2].parent is None:
                    el.append(prior[-1][2])
            else:
                for child in self.calls(a, b):
                    el.append(child)
        return el, close


def _object_pairs(src: str, start: int, end: int) -> Iterator[tuple[str, str]]:
    for a, b in _arg_spans(src, start, end):
        m = re.match(r"""^(?:['"]([^'"]+)['"]|([A-Za-z_$][\w$-]*))\s*:\s*(.*)$""", src[a:b], re.S)
        if m:
            yield (m.group(1) or m.group(2)), m.group(3).strip()


def js_trees(src: str, origin: str) -> list[El]:
    """Elements built with h() in a JS file; roots hang off a synthetic <body>."""
    trees = _JsTrees(src, origin)
    roots = trees.calls(0, len(src))
    html, body = new_document(origin)
    for el in roots:
        if el.parent is None:
            body.append(el)
    return [html]


def loader_tree(src: str, origin: str) -> list[El]:
    """Classic-script DOM building: createElement / className / setAttribute / appendChild."""
    els: dict[str, El] = {}
    _, body = new_document(origin)
    for m in re.finditer(r"var (\w+) = document\.createElement\('(\w+)'\)", src):
        els[m.group(1)] = El(m.group(2), origin=origin)
    for m in re.finditer(r"(\w+)\.className = '([^']*)'", src):
        if m.group(1) in els:
            els[m.group(1)].attrs["class"] = m.group(2)
    for m in re.finditer(r"(\w+)\.setAttribute\('([\w-]+)', '([^']*)'\)", src):
        if m.group(1) in els:
            els[m.group(1)].attrs[m.group(2)] = m.group(3)
    for m in re.finditer(r"(\w+)\.textContent = '([^']*)'", src):
        if m.group(1) in els:
            els[m.group(1)].text = m.group(2)
    for m in re.finditer(r"(\w+)\.appendChild\((\w+)\)", src):
        parent = (
            body if m.group(1) == "body" or m.group(1) == "document.body" else els.get(m.group(1))
        )
        child = els.get(m.group(2))
        if parent is not None and child is not None and child.parent is None:
            parent.append(child)
    for m in re.finditer(r"document\.body\.appendChild\((\w+)\)", src):
        if m.group(1) in els and els[m.group(1)].parent is None:
            body.append(els[m.group(1)])
    return [body.parent] if body.parent else []


CSS_NAME = re.compile(r"(?<![\w-])([.#])(-?[A-Za-z_][\w-]*)")
JS_CLASS = re.compile(
    r"""classList\.(?:add|toggle|remove|contains)\(\s*['"`]([\w -]+)['"`]|className\s*=\s*['"`]([\w -]+)['"`]"""
)


def loose_names(css: str, js: str, origin: str) -> list[El]:
    """Class and id names only seen in CSS or in classList calls, each as its own element."""
    _, body = new_document(origin)
    names: set[tuple[str, str]] = set()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"url\([^)]*\)", "", css)
    for block in re.findall(r"([^{}]+)\{", css):
        for kind, name in CSS_NAME.findall(block):
            if kind == "#" and re.fullmatch(r"[0-9a-fA-F]{3,8}", name):
                continue
            names.add((kind, name))
    for m in JS_CLASS.finditer(js):
        for name in (m.group(1) or m.group(2) or "").split():
            names.add((".", name))
    for kind, name in sorted(names):
        body.append(El("div", {"class": name} if kind == "." else {"id": name}, origin=origin))
    return [body.parent] if body.parent else []


def ui_elements(dirs: Sequence[Path]) -> list[El]:
    """Element trees from the HTML, JS and CSS files under `dirs` (a static
    scanner: it understands HTML, `h('tag', {...})` calls, classic createElement
    code, CSS selectors and classList literals, not JSX or bundles)."""
    roots: list[El] = []
    for d in dirs:
        for f in sorted(d.rglob("*")):
            if not f.is_file() or "__pycache__" in f.parts:
                continue
            origin = f.relative_to(d.parent).as_posix()
            text = f.read_text(encoding="utf-8") if f.suffix in (".html", ".js", ".css") else ""
            if f.suffix == ".html":
                roots.append(html_tree(text, origin))
            elif f.suffix == ".js":
                roots += js_trees(text, origin) + loader_tree(text, origin)
                roots += loose_names("", text, origin)
            elif f.suffix == ".css":
                roots += loose_names(text, "", origin)
    return [el for root in roots for el in root.walk()]


# --------------------------------------------------- CSS selector matching


class SelectorError(ValueError):
    pass


PSEUDO_ARG = {
    "not",
    "is",
    "matches",
    "where",
    "has",
    "-abp-has",
    "has-text",
    "contains",
    "-abp-contains",
    "nth-child",
    "nth-last-child",
    "nth-of-type",
    "nth-last-of-type",
}
PSEUDO_SIMPLE = {
    "first-child",
    "last-child",
    "only-child",
    "empty",
    "root",
    "first-of-type",
    "last-of-type",
    "only-of-type",
    "link",
    "any-link",
}
IDENT = r"-?(?:[A-Za-z_]|\\.|[^\x00-\x7f])(?:[\w-]|\\.|[^\x00-\x7f])*"


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def parse_selector_list(sel: str) -> list[list[tuple[str, list]]]:
    return [parse_complex(part) for part in _split_top(sel, ",")]


def _split_top(s: str, sep: str) -> list[str]:
    parts, depth, cur, i = [], 0, "", 0
    while i < len(s):
        ch = s[i]
        if ch in "\"'":
            j = _skip_string(s, i)
            cur += s[i:j]
            i = j
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur.strip())
    if any(not p for p in parts):
        raise SelectorError(s)
    return parts


def parse_complex(s: str) -> list[tuple[str, list]]:
    """[(combinator, compound), ...]; combinator of the first is ''."""
    out: list[tuple[str, list]] = []
    i, comb = 0, ""
    s = s.strip()
    if s and s[0] in ">+~":  # relative selector (inside :has)
        comb, i = s[0], 1
    while i < len(s):
        while i < len(s) and s[i] == " ":
            i += 1
        compound, i = _parse_compound(s, i)
        out.append((comb or ("" if not out else " "), compound))
        j = i
        while j < len(s) and s[j] == " ":
            j += 1
        if j < len(s) and s[j] in ">+~":
            comb, i = s[j], j + 1
        elif j > i or j == len(s):
            comb, i = " ", j
        else:
            raise SelectorError(s)
    if not out:
        raise SelectorError(s)
    return out


def _parse_compound(s: str, i: int) -> tuple[list, int]:
    parts: list = []
    m = re.compile(r"\*|" + IDENT).match(s, i)
    if m and s[i] not in ".#[:":
        parts.append(("tag", m.group(0).lower()))
        i = m.end()
    while i < len(s) and s[i] not in " >+~,":
        ch = s[i]
        if ch in ".#":
            m = re.compile(IDENT).match(s, i + 1)
            if not m:
                raise SelectorError(s)
            parts.append(("class" if ch == "." else "id", _unescape(m.group(0))))
            i = m.end()
        elif ch == "[":
            end = _match_close(s, i)
            parts.append(("attr", _parse_attr(s[i + 1 : end])))
            i = end + 1
        elif ch == ":":
            if s.startswith("::", i):
                raise SelectorError(s)  # pseudo-elements: not an element of ours
            m = re.compile(r"[\w-]+").match(s, i + 1)
            if not m:
                raise SelectorError(s)
            name, i = m.group(0).lower(), m.end()
            arg = None
            if i < len(s) and s[i] == "(":
                end = _match_close(s, i)
                arg, i = s[i + 1 : end], end + 1
            if name in PSEUDO_ARG and arg is not None:
                parts.append(("pseudo", (name, arg)))
            elif name in PSEUDO_SIMPLE and arg is None:
                parts.append(("pseudo", (name, None)))
            else:
                raise SelectorError(s)  # procedural or unknown: not evaluated
        else:
            raise SelectorError(s)
    if not parts:
        raise SelectorError(s)
    return parts, i


def _parse_attr(body: str) -> tuple[str, str, str, bool]:
    m = re.match(
        r"""^\s*([\w:-]+)\s*(?:([~|^$*]?=)\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s\]]+)\s*([iIsS])?)?\s*$""",
        body,
    )
    if not m:
        raise SelectorError(body)
    value = m.group(3) or ""
    if value[:1] in "\"'":
        value = value[1:-1]
    return m.group(1).lower(), m.group(2) or "", _unescape(value), (m.group(4) or "").lower() == "i"


ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _attr_ok(el: El, spec: tuple[str, str, str, bool]) -> bool:
    name, op, value, icase = spec
    if name not in el.attrs:
        return False
    have = el.attrs[name]
    if not op:
        return True
    if icase:  # ASCII case-insensitive, like CSS
        have, value = have.translate(ASCII_LOWER), value.translate(ASCII_LOWER)
    if op == "=":
        return have == value
    if op == "~=":
        return value in have.split()
    if op == "|=":
        return have == value or have.startswith(value + "-")
    if not value:
        return False
    return {"^=": have.startswith, "$=": have.endswith, "*=": have.__contains__}[op](value)


def _siblings(el: El) -> list[El]:
    return el.parent.children if el.parent else [el]


def _nth(arg: str, pos: int) -> bool:
    arg = arg.replace(" ", "").lower()
    if arg == "odd":
        return pos % 2 == 1
    if arg == "even":
        return pos % 2 == 0
    if arg.isdigit():
        return pos == int(arg)
    m = re.fullmatch(r"([+-]?\d*)n([+-]\d+)?", arg)
    if not m:
        return False
    a = int(m.group(1) + "1" if m.group(1) in ("", "+", "-") else m.group(1))
    b = int(m.group(2) or 0)
    return (pos - b) % a == 0 and (pos - b) // a >= 0 if a else pos == b


def _text_ok(el: El, arg: str) -> bool:
    text = el.all_text()
    if len(arg) > 2 and arg.startswith("/") and arg.rstrip("imsu").endswith("/"):
        try:
            return (
                re.search(
                    arg[1 : arg.rstrip("imsu").rindex("/")],
                    text,
                    re.I if "i" in arg[arg.rindex("/") :] else 0,
                )
                is not None
            )
        except re.error:
            return False
    return arg.strip("\"'") in text


def match_compound(parts: list, el: El) -> bool:
    for kind, v in parts:
        if kind == "tag":
            if v != "*" and el.tag != v:
                return False
        elif kind == "class":
            if v not in el.classes:
                return False
        elif kind == "id":
            if el.attrs.get("id") != v:
                return False
        elif kind == "attr":
            if not _attr_ok(el, v):
                return False
        else:
            name, arg = v
            sibs = _siblings(el)
            same = [s for s in sibs if s.tag == el.tag]
            if name == "not":
                if any(match_complex(c, el) for c in parse_selector_list(arg)):
                    return False
            elif name in ("is", "matches", "where"):
                if not any(match_complex(c, el) for c in parse_selector_list(arg)):
                    return False
            elif name in ("has", "-abp-has"):
                if not any(_has(el, parse_complex(part)) for part in _split_top(arg, ",")):
                    return False
            elif name in ("has-text", "contains", "-abp-contains"):
                if not _text_ok(el, arg):
                    return False
            elif name == "first-child" and sibs[0] is not el:
                return False
            elif name == "last-child" and sibs[-1] is not el:
                return False
            elif name == "only-child" and len(sibs) != 1:
                return False
            elif name == "first-of-type" and same[0] is not el:
                return False
            elif name == "last-of-type" and same[-1] is not el:
                return False
            elif name == "only-of-type" and len(same) != 1:
                return False
            elif name == "empty" and (el.children or el.text.strip()):
                return False
            elif name == "root" and el.parent is not None:
                return False
            elif name in ("link", "any-link") and not (el.tag == "a" and "href" in el.attrs):
                return False
            elif name.startswith("nth"):
                seq = same if name.endswith("of-type") else sibs
                pos = seq.index(el) + 1
                if "last" in name:
                    pos = len(seq) - pos + 1
                if not _nth(arg or "", pos):
                    return False
    return True


def _has(el: El, rel: list[tuple[str, list]]) -> bool:
    first_comb = rel[0][0] or " "
    if first_comb in (" ", ">"):
        pool = (
            [d for c in el.children for d in c.walk()] if first_comb == " " else list(el.children)
        )
    else:
        sibs = _siblings(el)
        after = sibs[sibs.index(el) + 1 :]
        pool = after[:1] if first_comb == "+" else after
    rest = [("", rel[0][1]), *rel[1:]]
    for cand in pool:
        if not match_compound(rest[0][1], cand):
            continue
        if len(rest) == 1:
            return True
        # remaining parts relative to cand: check descendants of cand
        tail = rest[1:]
        if any(
            match_complex([("", tail[-1][1])], d) and match_complex(rest, d) for d in cand.walk()
        ):
            return True
    return False


def match_complex(sel: list[tuple[str, list]], el: El) -> bool:
    """Right-to-left match of a complex selector with backtracking."""

    def rec(idx: int, node: El) -> bool:
        if not match_compound(sel[idx][1], node):
            return False
        if idx == 0:
            return True
        comb = sel[idx][0]
        if comb == ">":
            return node.parent is not None and rec(idx - 1, node.parent)
        if comb == " ":
            p = node.parent
            while p is not None:
                if rec(idx - 1, p):
                    return True
                p = p.parent
            return False
        sibs = _siblings(node)
        before = sibs[: sibs.index(node)]
        if comb == "+":
            return bool(before) and rec(idx - 1, before[-1])
        if comb == "~":
            return any(rec(idx - 1, s) for s in before)
        return False

    return rec(len(sel) - 1, el)


class _Index:
    def __init__(self, elements: list[El]) -> None:
        self.all = elements
        self.by_id: dict[str, list[El]] = {}
        self.by_class: dict[str, list[El]] = {}
        self.by_tag: dict[str, list[El]] = {}
        self.by_attr: dict[str, list[El]] = {}
        for el in elements:
            if el.attrs.get("id"):
                self.by_id.setdefault(el.attrs["id"], []).append(el)
            for c in el.classes:
                self.by_class.setdefault(c, []).append(el)
            self.by_tag.setdefault(el.tag, []).append(el)
            for a in el.attrs:
                self.by_attr.setdefault(a, []).append(el)

    def candidates(self, compound: list) -> list[El]:
        for kind, v in compound:
            if kind == "id":
                return self.by_id.get(v, [])
            if kind == "class":
                return self.by_class.get(v, [])
        for kind, v in compound:
            if kind == "attr":
                return self.by_attr.get(v[0], [])
            if kind == "tag" and v != "*":
                return self.by_tag.get(v, [])
        return self.all
