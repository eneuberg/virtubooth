"""Response and request shapes of the analysis admin API (PLAN §4.4)."""

from __future__ import annotations

from typing import Literal

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


class AnalysisStatus(BaseModel):
    worker: WorkerStatus
    counts: AnalysisCounts
    queue: AnalysisQueue
    analyzers: list[AnalyzerStatus]


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
    idx: int = Field(description="Position in the photo's object list (0-based).")
    label: str = Field(description="Canonical English label, e.g. „wine glass“.")
    label_de: str = Field(description="German label, e.g. „Weinglas“.")
    score: float
    box: ObjectBox | None
    source: str = Field(description="local | claude | mistral")
    model: str


class DetectionRun(BaseModel):
    source: str
    state: Literal["done", "failed", "skipped"]
    model: str | None
    error: str | None


class OptOutState(BaseModel):
    analysis: bool = Field(description="Live: the guest does not want the analysis.")
    external_ai: bool = Field(description="Live: the guest's photos never go to an external AI.")


class PropertyScores(BaseModel):
    name: str
    archived: bool
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
    objects: list[PhotoObject]
    runs: list[DetectionRun]
    opt_out: OptOutState
    opt_out_at_analysis: bool = Field(
        description="The guest had the analysis opt-out on when the photo was analysed."
    )
    properties: list[PropertyScores]
    durations_ms: dict[str, int]
