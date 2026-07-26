from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator
import uuid


class FragmentType(str, Enum):
    image = "image"
    headline = "headline"
    snippet = "snippet"
    metadata = "metadata"
    archive_screenshot = "archive_screenshot"


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    enriched = "enriched"
    failed = "failed"


class FragmentLayout(BaseModel):
    x: float  # 0–1 fraction of canvas width
    y: float  # 0–1 fraction of canvas height
    width: int  # px
    height: int  # px
    rotation: float  # degrees
    z_index: int
    css_filter: str
    blend_mode: str
    text_color: str = ""  # override color for text fragments, e.g. "#ffffff"


class Fragment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: FragmentType
    content: str  # URL for images/archive, raw text for text types
    source_url: str = ""
    source_domain: str = ""
    image_source: str = ""  # "openverse" | "wikimedia" | ""
    captured_at: str | None = None
    og: dict[str, Any] = Field(default_factory=dict)
    layout: FragmentLayout | None = None


class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    status: JobStatus = JobStatus.pending
    progress: int = 0  # 0–100
    error: str | None = None


class GenerateRequest(BaseModel):
    topic: str
    density: str | None = None  # "sparse" | "dense" | None
    layout_seed: int | None = None  # pin composition for reproducible / seed-series runs


class GenerateResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    status: JobStatus
    progress: int
    error: str | None = None


class CanvasConfig(BaseModel):
    width: int = 1800
    height: int = 1200


class CollageResponse(BaseModel):
    job_id: str
    topic: str
    seed: int  # topic hash (deterministic per topic)
    layout_seed: int | None = None  # the actual composition seed used for this collage
    canvas: CanvasConfig
    fragments: list[Fragment]


# ── ledger: the walker's private memory (topics + how each landed) ──────────────
class LedgerRecord(BaseModel):
    id: str | None = None            # server-assigned on append
    topic: str
    mode: str = ""                   # single | lift | graft | frame | ...
    source: str = ""                 # corpus source, when known (aic | met | text)
    shape: str = ""                  # topic form: 1w | 2w | 3w | 4w+ (diversity signal)
    components: list[str] = Field(default_factory=list)  # the topic's component words
    tags: list[str] = Field(default_factory=list)
    ts: float | None = None          # unix time recorded
    post_id: str | None = None       # Tumblr post id, once posted
    state: str | None = None         # draft | queue | published | ... (fate)
    notes: int | None = None         # Tumblr note_count (engagement), back-filled by sync

    # Tumblr returns post ids as JSON numbers, and pydantic v2 does not coerce int -> str.
    # Without this the whole ledger 422s on every posted record (and the client swallows it).
    @field_validator("post_id", mode="before")
    @classmethod
    def _post_id_to_str(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int) else v


class LedgerRecentResponse(BaseModel):
    records: list[LedgerRecord]


class LedgerFatePatch(BaseModel):
    post_id: str
    state: str | None = None
    notes: int | None = None

    @field_validator("post_id", mode="before")
    @classmethod
    def _patch_id_to_str(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int) else v
