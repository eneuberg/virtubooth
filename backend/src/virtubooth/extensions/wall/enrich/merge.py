"""Merging the object lists of the sources into the photo's one list (pure).

Each source keeps its own frozen list (`photo_source_objects`: the local model's,
the external AI's). The list the poller, the categories and the wall work on is
`photo_objects`, the merged list: it starts as the first source's list, and a
later source's object either LINKS to an entry already there (the same thing:
the same label, mapped to the COCO label set, and frames that overlap with
IoU ≥ LINK_IOU) or is APPENDED. So the merged list's idx never changes —
property scores index into it, and detection results may arrive after the
local ones — and the merge is deterministic: the same inputs give the same list.

Pairs are matched greedily, best overlap first (ties: the new object's position,
then the entry's idx), one to one, and an entry takes at most one object per
source. An object without a frame links to the first entry of its label that has
no frame match from this source yet only when that entry has no frame either.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .analyzers.objects import LABEL_DE

LINK_IOU = 0.5
Box = tuple[float, float, float, float]


class Found(Protocol):
    """A source's object (objects.DetectedObject)."""

    @property
    def label(self) -> str: ...
    @property
    def label_de(self) -> str: ...
    @property
    def score(self) -> float: ...
    @property
    def box(self) -> Box | None: ...


# other names (English, lower case, singular) for the COCO classes the local
# detector knows: an external AI says „smartphone“, the detector „cell phone“
SYNONYMS: dict[str, str] = {
    "man": "person", "woman": "person", "boy": "person", "girl": "person",
    "child": "person", "kid": "person", "baby": "person", "people": "person",
    "guest": "person", "human": "person", "adult": "person", "lady": "person",
    "guy": "person",
    "phone": "cell phone", "mobile phone": "cell phone", "smartphone": "cell phone",
    "mobile": "cell phone", "cellphone": "cell phone", "iphone": "cell phone",
    "wineglass": "wine glass", "glass of wine": "wine glass", "champagne glass": "wine glass",
    "champagne flute": "wine glass", "cocktail glass": "wine glass", "prosecco glass": "wine glass",
    "beer bottle": "bottle", "wine bottle": "bottle", "water bottle": "bottle",
    "champagne bottle": "bottle", "glass bottle": "bottle",
    "mug": "cup", "coffee cup": "cup", "coffee mug": "cup", "plastic cup": "cup",
    "paper cup": "cup", "tea cup": "cup", "teacup": "cup",
    "sofa": "couch", "settee": "couch",
    "television": "tv", "tv set": "tv", "monitor": "tv",
    "table": "dining table", "desk": "dining table",
    "plant": "potted plant", "houseplant": "potted plant", "flower pot": "potted plant",
    "bike": "bicycle", "motorbike": "motorcycle", "auto": "car",
    "laptop computer": "laptop", "notebook computer": "laptop",
    "purse": "handbag", "hand bag": "handbag", "bag": "handbag",
    "rucksack": "backpack",
    "puppy": "dog", "kitten": "cat",
    "teddy": "teddy bear", "stuffed animal": "teddy bear", "plush toy": "teddy bear",
    "hair dryer": "hair drier", "hairdryer": "hair drier", "blow dryer": "hair drier",
    "ball": "sports ball", "football": "sports ball", "soccer ball": "sports ball",
    "doughnut": "donut", "hotdog": "hot dog", "fridge": "refrigerator",
    "remote control": "remote", "computer mouse": "mouse", "necktie": "tie",
}  # fmt: skip

# German names (lower case) for the COCO classes: the AI's label_de and the
# detector's German labels, plus common synonyms
GERMAN: dict[str, str] = {de.lower(): en for en, de in LABEL_DE.items()} | {
    "mensch": "person", "frau": "person", "mann": "person", "kind": "person",
    "junge": "person", "mädchen": "person", "gast": "person",
    "smartphone": "cell phone", "telefon": "cell phone", "mobiltelefon": "cell phone",
    "sektglas": "wine glass", "champagnerglas": "wine glass", "cocktailglas": "wine glass",
    "bierflasche": "bottle", "weinflasche": "bottle", "sektflasche": "bottle",
    "wasserflasche": "bottle", "tasse": "cup", "kaffeetasse": "cup", "plastikbecher": "cup",
    "couch": "couch", "monitor": "tv",
    "pflanze": "potted plant", "zimmerpflanze": "potted plant", "rad": "bicycle",
    "tasche": "handbag", "hündchen": "dog", "welpe": "dog", "fön": "hair drier",
    "haartrockner": "hair drier", "fußball": "sports ball", "krapfen": "donut",
    "berliner": "donut", "kühlschrank": "refrigerator",
}  # fmt: skip

_SPACE = re.compile(r"\s+")


def _plain(label: str) -> str:
    return _SPACE.sub(" ", label.strip().lower().replace("_", " ").replace("-", " "))


def _singular(word: str) -> str:
    """A rough English singular of the last word ("glasses" stays: eyewear)."""
    for plural, single in (("ies", "y"), ("ches", "ch"), ("shes", "sh"), ("xes", "x")):
        if word.endswith(plural) and len(word) > len(plural) + 1:
            return word[: -len(plural)] + single
    if word.endswith("s") and not word.endswith(("ss", "us", "is", "glasses")) and len(word) > 3:
        return word[:-1]
    return word


def coco_label(label: str, label_de: str = "") -> str | None:
    """The COCO class `label` (or the German `label_de`) names, None when none."""
    plain = _plain(label)
    for cand in (plain, _singular(plain)):
        if cand in LABEL_DE:
            return cand
        if cand in SYNONYMS:
            return SYNONYMS[cand]
    de = _plain(label_de)
    return GERMAN.get(de) if de else None


def canonical(label: str, label_de: str = "") -> tuple[str, str]:
    """(label, label_de) for the merged list: the COCO class when the object is
    one (so `objects.count:cell phone` counts the AI's „smartphone“ too), else
    the source's own cleaned label; the source's German name stays (the COCO
    class's when it gave none)."""
    coco = coco_label(label, label_de)
    if coco is not None:
        return coco, label_de.strip() or LABEL_DE[coco]
    plain = _plain(label)
    return plain or label, label_de.strip() or label


def same_thing(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """Whether two (label, label_de) name the same kind of thing."""
    ca, cb = coco_label(*a), coco_label(*b)
    if ca is not None or cb is not None:
        return ca == cb
    if _singular(_plain(a[0])) == _singular(_plain(b[0])):
        return True
    return bool(a[1].strip()) and _plain(a[1]) == _plain(b[1])


def iou(a: Box, b: Box) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0.0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0.0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


@dataclass(frozen=True)
class Entry:
    """An entry of the merged list as the merge sees it."""

    idx: int
    label: str
    label_de: str
    box: Box | None
    sources: frozenset[str]


def plan(existing: Sequence[Entry], new: Sequence[Found], source: str) -> list[int | None]:
    """For each object of `new` (a source's list, in its order): the idx of the
    entry it links to, or None (appended)."""
    free = [e for e in existing if source not in e.sources]
    pairs: list[tuple[float, int, int]] = []
    for i, o in enumerate(new):
        if o.box is None:
            continue
        for e in free:
            if e.box is None or not same_thing((o.label, o.label_de), (e.label, e.label_de)):
                continue
            overlap = iou(o.box, e.box)
            if overlap >= LINK_IOU:
                pairs.append((-overlap, i, e.idx))
    out: list[int | None] = [None] * len(new)
    taken: set[int] = set()
    for _, i, idx in sorted(pairs):
        if out[i] is None and idx not in taken:
            out[i] = idx
            taken.add(idx)
    # objects without a frame: the first frameless entry of the same kind
    for i, o in enumerate(new):
        if o.box is not None:
            continue
        for e in free:
            if e.idx in taken or e.box is not None:
                continue
            if same_thing((o.label, o.label_de), (e.label, e.label_de)):
                out[i] = e.idx
                taken.add(e.idx)
                break
    return out


@dataclass(frozen=True)
class Merged:
    """An entry of a merged list built in memory (the test image's preview)."""

    idx: int
    label: str
    label_de: str
    score: float
    box: Box | None
    # source → position of its object in that source's list
    parts: dict[str, int]


def merge_lists(lists: Sequence[tuple[str, Sequence[Found]]]) -> list[Merged]:
    """The merged list of `lists` ((source, objects) in arrival order), exactly
    as the database would build it."""
    out: list[Merged] = []
    for source, objs in lists:
        entries = [Entry(m.idx, m.label, m.label_de, m.box, frozenset(m.parts)) for m in out]
        links = plan(entries, objs, source)
        for pos, (o, link) in enumerate(zip(objs, links, strict=True)):
            if link is not None:
                out[link].parts[source] = pos
                continue
            label, label_de = canonical(o.label, o.label_de)
            out.append(Merged(len(out), label, label_de, o.score, o.box, {source: pos}))
    return out
