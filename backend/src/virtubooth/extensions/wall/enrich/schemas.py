"""Response and request shapes of the analysis admin API (PLAN §4.4)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

WorkerState = Literal["running", "starting", "stopped", "off", "crashed"]
AnalysisState = Literal["pending", "running", "done", "failed", "skipped"]


class WorkerStatus(BaseModel):
    state: WorkerState
    ml: bool = Field(description="The worker has the ML packages (`ml` extra).")
    message: str | None = Field(description="German hint for the admin, e.g. missing models.")
    last_beat_at: str | None
    processed: int | None = Field(
        description="Photos the running worker analysed since it started; null without a fresh heartbeat."
    )
    rss_mb: int | None = Field(
        description="The worker's memory (resident set, MB); null without a fresh heartbeat."
    )
    load_errors: dict[str, str] = Field(
        description="Analyzers whose models failed to load: name -> error. Empty without a fresh heartbeat."
    )


class AnalysisCounts(BaseModel):
    pending: int
    running: int
    done: int
    failed: int
    skipped: int
    total: int


class AnalyzerStats(BaseModel):
    processed: int = Field(description="Photos this analyzer ran on (worker heartbeat).")
    errors: int = Field(description="Photos that failed in this analyzer.")
    avg_ms: float | None = Field(description="Average duration (recent photos weigh most).")
    last_ms: float | None = Field(description="Duration on the last photo.")


class AnalyzerSettingSpec(BaseModel):
    key: str
    title: str = Field(description="German.")
    min: float
    max: float
    step: float


class AnalyzerStatus(BaseModel):
    name: str
    title: str
    kind: Literal["basic", "ml"]
    version: str
    enabled: bool
    available: bool
    reason: str | None = Field(description="Why it cannot run (German); null when available.")
    facts: list[str]
    description: str = Field(description="What it does (German, one sentence).")
    size_mb: float = Field(description="Its model files on disk (MB); 0 without models.")
    stats: AnalyzerStats
    settings: dict[str, float] | None = Field(
        description="Its current settings; null when it has none."
    )
    settings_schema: list[AnalyzerSettingSpec]


class AnalysisQueue(BaseModel):
    pending: int = Field(description="Photos waiting for their analysis.")
    running: int
    oldest_pending_s: int | None = Field(description="Age of the oldest waiting photo (s).")


class ModelDownload(BaseModel):
    """„Modelle herunterladen“: the app's download of the missing model files."""

    state: Literal["idle", "running", "done", "failed"]
    current: str | None = Field(description="The model being downloaded right now.")
    models: list[str] = Field(description="The models this download fetches.")
    done_bytes: int
    total_bytes: int
    error: str | None = Field(description="Why it failed (German).")
    finished_at: str | None


class ModelsStatus(BaseModel):
    """The model files the enabled and the standard analyzers need, as the app
    sees them in its data dir (the worker reports its own view per analyzer)."""

    ml: bool = Field(description="The ML packages are installed (image built with VB_ML=1).")
    missing: list[str] = Field(description="Needed models that are not on the server.")
    missing_mb: float = Field(description="Their download size (MB).")
    dest: str = Field(description="Where downloads go (persistent: in the data volume).")
    can_download: bool = Field(
        description="POST /admin/analysis/models/download would fetch something now."
    )
    download: ModelDownload


class AnalysisStatus(BaseModel):
    worker: WorkerStatus
    counts: AnalysisCounts
    queue: AnalysisQueue
    analyzers: list[AnalyzerStatus]
    models: ModelsStatus
    image: Literal["original", "filtered"] = Field(
        description="„Erkennung auf“: which image the analysis (every analyzer and the "
        "AI's detection) reads for new photos; photos without an original use the photo."
    )


class AnalysisImageIn(BaseModel):
    use: Literal["original", "filtered"]


class AnalyzersIn(BaseModel):
    disabled: list[str] = Field(
        max_length=50, description="The complete set of analyzers to switch off."
    )


class AnalyzerIn(BaseModel):
    enabled: bool
    settings: dict[str, float] | None = Field(
        None, description="Only the keys of its `settings_schema`; omitted = unchanged."
    )


class AnalysisBox(BaseModel):
    kind: Literal["face", "hand", "person", "object"]
    x: float = Field(description="0..1 from the left")
    y: float = Field(description="0..1 from the top")
    w: float
    h: float
    label: str
    score: float


class DetailLine(BaseModel):
    label: str
    value: str


class ObjectBox(BaseModel):
    x: float = Field(description="0..1 from the left")
    y: float = Field(description="0..1 from the top")
    w: float
    h: float


class PhotoObject(BaseModel):
    """An entry of the photo's MERGED object list (what the poll rates)."""

    idx: int = Field(description="Position in the photo's object list (0-based).")
    label: str = Field(description="Canonical English label, e.g. „wine glass“.")
    label_de: str = Field(description="German label, e.g. „Weinglas“.")
    score: float
    box: ObjectBox | None
    source: str = Field(description="The source that added it: local | claude | mistral")
    model: str
    sources: list[str] = Field(
        description="Every source whose object is this entry (local and an AI: both found it)."
    )


class SourceObject(BaseModel):
    """An object as one source found it (its own list, frozen)."""

    pos: int = Field(description="Position in this source's own list (0-based).")
    label: str = Field(description="As the source named it.")
    label_de: str
    score: float
    box: ObjectBox | None
    source: str = Field(description="local | claude | mistral")
    model: str
    merged_idx: int = Field(description="The entry of `objects` (merged) it became or is.")


class DetectionRun(BaseModel):
    source: str
    state: Literal["done", "failed", "skipped"]
    model: str | None
    error: str | None
    image: Literal["original", "filtered", "photo"] | None = Field(
        None,
        description="The image it looked at: the unfiltered original, the filtered photo "
        "(„Erkennung auf: Gefiltertes Foto“) or the photo (no separate original); null "
        "before v15.",
    )


class OptOutState(BaseModel):
    analysis: bool = Field(description="Live: the guest does not want the analysis.")
    external_ai: bool = Field(description="Live: the guest's photos never go to an external AI.")


class PropertyScores(BaseModel):
    name: str
    inactive: bool = Field(
        description="Not polled right now (no enabled category reads it, or in the Papierkorb)."
    )
    scores: list[float | None] = Field(description="Index = the object's idx.")


class PhotoAnalysis(BaseModel):
    photo_id: str = Field(description="The photo's public id.")
    state: AnalysisState
    attempts: int
    error: str | None
    finished_at: str | None
    versions: dict[str, str]
    facts: dict[str, float]
    boxes: list[AnalysisBox]
    details: list[DetailLine]
    objects: list[PhotoObject] = Field(
        description="The merged list (local and AI, deduplicated): what the poll rates and "
        "the categories count."
    )
    objects_local: list[SourceObject] = Field(description="The local model's own list.")
    objects_ai: list[SourceObject] = Field(
        description="The external AI's own list (Claude, Mistral; source and model per object)."
    )
    runs: list[DetectionRun]
    objects_fallback: str | None = Field(
        description="The local detector stood in for the external AI on this photo: why "
        "(German, e.g. „Budget aufgebraucht“); None otherwise."
    )
    opt_out: OptOutState
    opt_out_at_analysis: bool = Field(
        description="The guest had the analysis opt-out on when the photo was analysed."
    )
    properties: list[PropertyScores]
    durations_ms: dict[str, int]


class SummaryObject(BaseModel):
    """An entry of the merged object list."""

    label: str = Field(
        description="The English key (the COCO class when it is one); the Live tile "
        "colours the frame by it, so the same thing has the same colour everywhere."
    )
    label_de: str
    source: str = Field(description="The source that added it: local | claude | mistral")
    sources: list[str] = Field(description="Every source that found it.")
    score: float = Field(description="0..1, to 2 places.")
    box: ObjectBox | None = Field(
        description="On the full photo (0..1, to 3 places); null when the source gives none."
    )


class SummaryBox(BaseModel):
    """A face or hand frame for a tile (on the full photo, 0..1, to 3 places)."""

    kind: Literal["face", "hand"]
    x: float
    y: float
    w: float
    h: float


class CategoryWin(BaseModel):
    id: str = Field(description="The category's id.")
    emoji: str
    title: str
    verdict: bool = Field(description="The AI commented on it in this category.")
    rank: int = Field(1, description="Its place among the category's winners (1 = best).")
    headline: str = Field("", description="The object's name or the value text.")
    detail: str | None = Field(None, description="The value text when the headline is an object.")
    object_label: str | None = Field(None, description="The focus object's German name, if any.")
    comment: CategoryCommentOut | None = Field(
        None, description="The AI's cached comment on this photo in this category."
    )


class PhotoAnalysisSummary(BaseModel):
    """What the Live screen shows on and under a photo tile: the state, the key
    facts, the objects (label, score, frame), the face and hand frames, the guest's
    opt-outs and the categories it currently wins. The full analysis (details,
    runs, scores) is `/admin/photos/{id}/analysis`."""

    photo_id: str
    state: AnalysisState
    facts: dict[str, float] = Field(
        description="Only the key values: people, faces, smiles, happy_max, hands, "
        "thumbs_up, peace, rock, glasses, hats, age_groups (those measured)."
    )
    objects: list[SummaryObject]
    boxes: list[SummaryBox] = Field(description="Face and hand frames (objects carry their own).")
    opt_out: OptOutState
    objects_off: bool = Field(
        False,
        description="Analysed while object detection was „Aus“ (every detection run "
        "skipped as switched off, no objects): „Objekterkennung aus“, not „Nichts erkannt“.",
    )
    wins: list[CategoryWin]


class AnalysisSummariesOut(BaseModel):
    items: list[PhotoAnalysisSummary] = Field(
        description="In request order; unknown or deleted photos are left out."
    )


# ------------------------------------------- categories (v2: measures, rank, caption)

CategoryOp = Literal["gt", "lt", "gte", "lte", "eq", "ne", "between", "exists", "not_exists"]
Aggregate = Literal["count", "max", "min", "mean", "sum", "top_k_mean", "count_ge"]
CaptionFormat = Literal["count", "percent", "decimal", "number", "time", "text", "none"]
Order = Literal["desc", "asc"]
Effort = Literal["low", "medium", "high"]


class MeasureValue(BaseModel):
    """A photo value: an analyzer's fact, `photo.created_at` or `photo.guest_photos`."""

    kind: Literal["value"]
    key: str


class ObjectFilter(BaseModel):
    labels: list[str] = Field(
        default_factory=list, description="Only these labels (any of them); empty = all."
    )
    exclude: list[str] = Field(default_factory=list, description="Never these labels.")
    min_confidence: float | None = Field(None, description="0–1: only objects at least this sure.")


class MeasureObjects(BaseModel):
    """An aggregate over the photo's objects (after `where`): `count` (without a
    field: the objects; with one: those with a value), `max`, `min`, `mean`,
    `sum`, `top_k_mean` (k 2–5), `count_ge` (t 0–1) of `field`."""

    kind: Literal["objects"]
    where: ObjectFilter = Field(default_factory=ObjectFilter)
    field: str | None = Field(None, description="`confidence` or `prop:<name>`; null for count.")
    agg: Aggregate
    k: int | None = None
    t: float | None = None


Measure = Annotated[MeasureValue | MeasureObjects, Field(discriminator="kind")]


class CategoryCondition(BaseModel):
    measure: Measure
    op: CategoryOp
    operand: float | tuple[float, float] | None = Field(
        None, description="number (gt…ne), [a, b] (between), null (exists, not_exists)."
    )


class CategoryThen(BaseModel):
    by: Measure
    order: Order = "desc"


class CategoryRank(BaseModel):
    by: Measure = Field(description="Missing values rank last.")
    order: Order = "desc"
    threshold: float | None = Field(
        None, description="Only photos with `by` ≥ threshold (desc) or ≤ threshold (asc)."
    )
    then_by: list[CategoryThen] = Field(default_factory=list, description="≤ 2 tie-breakers.")


class CategorySelect(BaseModel):
    count: int = Field(3, description="1–10 winners.")
    one_per_guest: bool = True


class CategoryCaption(BaseModel):
    value: Measure | None = Field(
        None, description="The value shown (and required); null = `rank.by`."
    )
    format: CaptionFormat = "count"
    one: str = Field("", description="Singular word, the unit (decimal) or the text (text).")
    many: str = Field("", description="Plural word.")
    show_object: bool = Field(
        False, description="The headline is the focus object's name (the value its detail)."
    )


class CategoryVerdictSpec(BaseModel):
    """The AI comments on the top `count` winners (one each); it never ranks."""

    prompt: str | None = Field(
        None, description="≤ 1000 chars: the host's task; null = the default."
    )
    count: int = Field(3, description="1–5 comments (the best winners).")
    model: str | None = Field(
        None, description="A Haiku- or Sonnet-class model (`LlmStatus.verdict.models`); null = "
        "the provider's cheapest."
    )  # fmt: skip
    effort: Effort = "low"


class CategorySpec(BaseModel):
    """A rule-based wall category, spec version 2. Invalid input → 400
    `invalid_category` naming the field in German. Writes also take a spec in the
    old version 1 shape (deprecated: converted)."""

    version: Literal[2] = 2
    emoji: str = Field(description="One emoji.")
    title: str = Field(description="1–40 chars.")
    line: str = Field("", description="0–80 chars; empty = the explanation is generated.")
    pool: list[CategoryCondition] = Field(
        default_factory=list, description="0–8 conditions, all must hold."
    )
    rank: CategoryRank
    select: CategorySelect = Field(default_factory=CategorySelect)
    caption: CategoryCaption = Field(default_factory=CategoryCaption)
    verdict: CategoryVerdictSpec | None = None


# ------------------------------------------------------ category answers


class WinnerObject(BaseModel):
    """The focus object of a winner (what the wall frames)."""

    idx: int = Field(description="Its idx in the photo's merged object list.")
    label: str
    label_de: str
    value: float | None = Field(description="The measure's value for it (score or confidence).")
    box: ObjectBox | None = Field(description="0..1 on the analysed (= shown) photo; null: none.")


class CategoryCommentOut(BaseModel):
    text: str = Field(description="German, ≤ 160 chars: the AI's comment on this winner.")
    emoji: str | None


class CategoryWinnerOut(BaseModel):
    photo_id: str
    thumb_url: str
    value: float | None
    label: str = Field(description="headline and detail together („Sonnenbrille · 0,93 …“).")
    headline: str = Field(description="The object's name (show_object) or the value text.")
    detail: str | None = Field(description="The value text when the headline is an object.")
    object_idx: int | None = Field(description="The focus object's idx, if any.")
    object: WinnerObject | None
    comment: CategoryCommentOut | None = Field(
        description="The AI's cached comment on this winner (the best `verdict.count` only)."
    )


class CategoryVerdictOut(BaseModel):
    """Deprecated: the best-ranked winner's comment (`winners[].comment`)."""

    text: str = Field(description="German, ≤ 160 chars.")
    emoji: str | None
    photo_id: str | None = Field(description="Public id of the photo it is about, or null.")


OffReason = Literal["ai_off", "property_trashed", "property_missing", "migrated_inactive"]


class CategoryLockOut(BaseModel):
    """Why the category cannot be switched on right now (409 `category_locked`)."""

    reason: Literal["ai_off", "property_trashed", "property_missing"]
    property: str | None
    message: str = Field(description="German.")


class CategoryItem(BaseModel):
    id: str
    enabled: bool
    preset: str | None = Field(description="The preset it came from; null = made by the host.")
    position: int
    spec: CategorySpec
    explanation: str = Field(description="The ranking in plain German (the wall's subtitle "
                             "when `line` is empty).")  # fmt: skip
    needs_ai: bool = Field(description="It reads an LLM property (external AI).")
    properties: list[str] = Field(description="The properties it reads.")
    locked: CategoryLockOut | None = Field(
        description="Why it cannot be switched on (the switch is disabled), or null."
    )
    off_reason: OffReason | None = Field(
        description="Switched off by the app (not the host), why; cleared when the host "
        "switches it."
    )
    off_detail: str | None = Field(description="The property the reason is about.")
    off_at: str | None
    available: bool
    reason: str | None = Field(description="Why it cannot win anything (German), or null.")
    verdict_paused: bool = Field(
        description="It has an AI verdict but the AI is not ready: no comments meanwhile."
    )
    verdict: CategoryVerdictOut | None
    winners: list[CategoryWinnerOut] = Field(description="Right now, best first (≤ count).")


class CategoriesOut(BaseModel):
    categories: list[CategoryItem]


class CategoryOrderIn(BaseModel):
    ids: list[str] = Field(max_length=200, description="First in this order; the rest after.")


class CategoryPreviewOut(BaseModel):
    winners: list[CategoryWinnerOut]
    matched: int = Field(description="Visible photos in the pool that pass the threshold.")
    reason: str | None = Field(description="Why it cannot win (German), or null.")
    explanation: str = Field(description="The ranking in plain German.")
    spec: CategorySpec = Field(description="The spec as validated (v2; a v1 input converted).")
    locked: CategoryLockOut | None = Field(
        description="It could be saved, but only switched off (and why)."
    )


class RestoreOut(BaseModel):
    added: list[str]


class OkOut(BaseModel):
    ok: Literal[True]


# ------------------------------------------------------ export / import


class CategoryFileProperty(BaseModel):
    name: str
    prompt: str


class CategoryFileEntry(BaseModel):
    id: str
    enabled: bool
    preset: str | None
    spec: CategorySpec


class CategoriesFile(BaseModel):
    """„Exportieren“: the categories and the properties they read (by name)."""

    format: Literal["virtubooth-categories"]
    version: Literal[2]
    exported_at: str
    properties: list[CategoryFileProperty] = Field(
        description="Each property a category reads, with its prompt."
    )
    categories: list[CategoryFileEntry]


class ImportedCategory(BaseModel):
    id: str = Field(description="Its id here (a copy: a free one, `<id>_2` …).")
    title: str
    enabled: bool
    from_id: str | None = Field(description="The id in the file when it was taken as a copy.")
    replaced: bool = Field(description="It overwrote the category with that id.")


class SkippedCategory(BaseModel):
    id: str = Field(description="The id in the file, or „Eintrag 3“.")
    reason: str = Field(description="German.")


class SwitchedOffCategory(BaseModel):
    id: str
    reason: Literal["ai_off", "property_trashed", "property_missing"]
    detail: str | None = Field(description="The property it is about.")
    message: str = Field(description="German.")


class CategoryImportOut(BaseModel):
    imported: list[ImportedCategory]
    skipped: list[SkippedCategory]
    properties_created: list[str] = Field(description="Created from the file (or a preset).")
    prompt_conflicts: list[str] = Field(
        description="Properties that exist here with another prompt: theirs stays."
    )
    switched_off: list[SwitchedOffCategory] = Field(
        description="Imported switched off although the file had them on (or a property "
        "is missing), and why."
    )
    notes: list[str] = Field(description="German hints (e.g. an old file's `active`).")
