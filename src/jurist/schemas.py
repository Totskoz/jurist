"""All Pydantic types used across the backend."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------- Trace events ----------------

class TraceEvent(BaseModel):
    """A single event in an agent trace. Orchestrator fills agent/run_id/ts."""

    type: str
    agent: str = ""
    run_id: str = ""
    ts: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------- Knowledge graph ----------------

class ArticleNode(BaseModel):
    article_id: str
    bwb_id: str
    label: str
    title: str
    body_text: str
    outgoing_refs: list[str] = Field(default_factory=list)


class ArticleEdge(BaseModel):
    from_id: str
    to_id: str
    kind: Literal["explicit", "regex"] = "explicit"
    context: str | None = None


# ---------------- Retriever outputs ----------------

class CitedArticle(BaseModel):
    bwb_id: str
    article_id: str
    article_label: str
    body_text: str
    reason: str


class CitedCase(BaseModel):
    ecli: str
    court: str
    date: str
    snippet: str
    similarity: float
    reason: str
    chunk_text: str              # M4: full best-chunk text; synthesizer quote-verification surface
    url: str


# ---------------- Case chunk storage (M3a) ----------------

class CaseChunkRow(BaseModel):
    """One LanceDB row: a chunked uitspraak passage + its bge-m3 embedding.

    Logical primary key: (ecli, chunk_idx). LanceDB does not enforce
    uniqueness; the ingester deduplicates on write.
    """

    # identity
    ecli: str
    chunk_idx: int

    # metadata (from RDF)
    court: str
    date: str                    # ISO 8601
    zaaknummer: str
    subject_uri: str
    modified: str                # ISO 8601 last-modified

    # content
    text: str
    embedding: list[float]       # 1024-d bge-m3, L2-normalized

    # display
    url: str


# ---------------- Agent I/O ----------------

class DecomposerIn(BaseModel):
    question: str


class DecomposerOut(BaseModel):
    sub_questions: list[str]
    concepts: list[str]
    intent: Literal["legality_check", "calculation", "procedure", "other"]


class StatuteRetrieverIn(BaseModel):
    sub_questions: list[str]
    concepts: list[str]
    intent: str


class StatuteRetrieverOut(BaseModel):
    cited_articles: list[CitedArticle]


class CaseRetrieverIn(BaseModel):
    question: str                    # M3b — user's original wording, threaded by orchestrator
    sub_questions: list[str]
    statute_context: list[CitedArticle]


class CaseRetrieverOut(BaseModel):
    cited_cases: list[CitedCase]


# ---------------- Structured answer ----------------

class WetArtikelCitation(BaseModel):
    article_id: str              # M4: fully-qualified; closed-set enum
    bwb_id: str
    article_label: str
    quote: str
    explanation: str


class UitspraakCitation(BaseModel):
    ecli: str
    quote: str
    explanation: str


class StructuredAnswer(BaseModel):
    kind: Literal["answer", "insufficient_context"] = "answer"
    korte_conclusie: str = Field(..., min_length=40, max_length=2000)
    relevante_wetsartikelen: list[WetArtikelCitation] = Field(default_factory=list)
    vergelijkbare_uitspraken: list[UitspraakCitation] = Field(default_factory=list)
    aanbeveling: str = Field(..., min_length=40, max_length=2000)
    insufficient_context_reason: str | None = Field(default=None, min_length=40, max_length=1000)

    @model_validator(mode="after")
    def _kind_matches_shape(self) -> StructuredAnswer:
        if self.kind == "answer":
            if self.insufficient_context_reason is not None:
                raise ValueError(
                    "insufficient_context_reason must be None when kind='answer'"
                )
            if not self.relevante_wetsartikelen:
                raise ValueError(
                    "relevante_wetsartikelen must be non-empty when kind='answer'"
                )
            if not self.vergelijkbare_uitspraken:
                raise ValueError(
                    "vergelijkbare_uitspraken must be non-empty when kind='answer'"
                )
        else:  # kind == "insufficient_context"
            if not self.insufficient_context_reason:
                raise ValueError(
                    "insufficient_context_reason required when kind='insufficient_context'"
                )
        return self


class SynthesizerIn(BaseModel):
    question: str
    cited_articles: list[CitedArticle]
    cited_cases: list[CitedCase]


class SynthesizerOut(BaseModel):
    answer: StructuredAnswer


# ---------------- Validator ----------------

class ValidatorIn(BaseModel):
    question: str
    answer: StructuredAnswer
    cited_articles: list[CitedArticle]
    cited_cases: list[CitedCase]


class ValidatorOut(BaseModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)


# ---------------- KG snapshot (M1) ----------------

class KGSnapshot(BaseModel):
    generated_at: str
    source_versions: dict[str, str]
    nodes: list[ArticleNode]
    edges: list[ArticleEdge]
