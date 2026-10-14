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


class AnalyzerStatus(BaseModel):
    name: str
    title: str
    kind: Literal["basic", "ml"]
    version: str
    enabled: bool
    available: bool
    reason: str | None = Field(description="Why it cannot run (German); null when available.")
    facts: list[str]


class AnalysisStatus(BaseModel):
    worker: WorkerStatus
    counts: AnalysisCounts
    analyzers: list[AnalyzerStatus]


class AnalyzersIn(BaseModel):
    disabled: list[str] = Field(
        max_length=50, description="The complete set of analyzers to switch off."
    )


class RerunIn(BaseModel):
    scope: Literal["failed", "all"]


class RerunOut(BaseModel):
    queued: int


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
