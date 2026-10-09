"""Project-owned data models. No SDK imports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceState = Literal["preparing", "processing", "ready", "error", "unknown"]
SourceKind = Literal["url", "youtube", "text", "file", "drive", "unknown"]
ArtifactKind = Literal["audio_overview", "report", "study_guide", "quiz", "flashcards"]
ArtifactKindAny = Literal[
    "audio_overview",
    "report",
    "study_guide",
    "quiz",
    "flashcards",
    "video",
    "mind_map",
    "infographic",
    "slide_deck",
    "data_table",
    "unknown",
]
TaskState = Literal["pending", "in_progress", "completed", "failed", "not_found", "unknown"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Notebook(_Model):
    id: str
    title: str
    source_count: int
    created_at: datetime | None
    modified_at: datetime | None
    is_owner: bool


class NotebookList(_Model):
    items: list[Notebook]


class NotebookDetail(_Model):
    notebook: Notebook
    summary: str | None


class Source(_Model):
    id: str
    notebook_id: str
    title: str | None
    kind: SourceKind
    state: SourceState
    url: str | None
    word_count: int | None
    created_at: datetime | None


class SourceList(_Model):
    items: list[Source]


class SourceDetail(_Model):
    source: Source
    text: str | None
    truncated: bool


_KIND_FIELD = {"url": "url", "text": "text", "file": "path", "drive": "drive_document_id"}


class AddSourceRequest(_Model):
    notebook_id: str
    kind: Literal["url", "text", "file", "drive"]
    url: str | None = None
    text: str | None = None
    title: str | None = None
    path: str | None = None
    drive_document_id: str | None = None
    wait: bool = False

    @model_validator(mode="after")
    def _check_kind_field(self) -> AddSourceRequest:
        field = _KIND_FIELD[self.kind]
        if getattr(self, field) is None:
            raise ValueError(f"kind={self.kind} requires {field}")
        return self


class Passage(_Model):
    source_id: str
    text: str
    rank: int


class PassageList(_Model):
    items: list[Passage]


class Citation(_Model):
    source_id: str
    number: int | None
    text: str | None


class ChatAnswer(_Model):
    answer: str
    conversation_id: str
    turn_number: int
    citations: list[Citation]


class GenerateRequest(_Model):
    notebook_id: str
    kind: ArtifactKind
    source_ids: list[str] | None = None
    instructions: str | None = None
    language: str = "en"
    options: dict[str, str] = Field(default_factory=dict)


class TaskStatus(_Model):
    task_id: str
    state: TaskState
    artifact_id: str | None
    error: str | None


class Artifact(_Model):
    id: str
    notebook_id: str
    title: str
    kind: ArtifactKindAny
    state: TaskState
    created_at: datetime | None
    url: str | None


class ArtifactList(_Model):
    items: list[Artifact]


class DownloadedFile(_Model):
    artifact_id: str
    path: str
    bytes: int


class Deleted(_Model):
    id: str
    kind: Literal["notebook", "source"]


class UsageWindow(_Model):
    kind: Literal["five_hour", "weekly", "unknown"]
    used_percent: float
    remaining_percent: float
    resets_at: datetime | None


class Usage(_Model):
    tenant_id: str
    notebooks_used: int
    notebook_limit: int | None
    source_limit: int | None
    windows: list[UsageWindow]
    session_ok: bool
