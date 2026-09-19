"""Shared data contracts for Kagaz.

Every agent and tool in this repo produces or consumes one of these models.
Define behavior against these types, not against raw dicts — they are the
seam between the LLM-driven agents and the deterministic Python tools.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class RequiredDoc(BaseModel):
    """One document a scheme's portal requires, as extracted from the
    scheme notification."""

    doc_type: str
    file_formats: list[str] = Field(default_factory=list)
    max_size_kb: int | None = None
    dimensions_px: tuple[int, int] | None = None
    must_be_valid_on: date | None = None
    notes: str | None = None


class Requirement(BaseModel):
    """Output of the requirement extractor: what a scheme actually asks for."""

    scheme_id: str
    scheme_name: str
    deadline: date | None = None
    required_documents: list[RequiredDoc] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    # "text" added for the pasted-text extraction path (spec section 6.1's
    # PDF -> pasted text -> manual priority never included a URL-fetch path
    # — "no URL fetching, no scraping" — so "url" stays reserved/unused
    # while "text" covers the real second tier).
    source: Literal["pdf", "url", "manual", "text"]
    confidence: float
    unresolved: list[str] = Field(default_factory=list)


class ExtractedDocument(BaseModel):
    """Output of a document verifier: what was actually found in one
    student document."""

    doc_type: str
    source_path: Path
    fields: dict[str, str] = Field(default_factory=dict)
    issue_date: date | None = None
    valid_until: date | None = None
    extraction_confidence: float


class Finding(BaseModel):
    """The unit of the audit report. needs_human=True is the only thing
    that triggers escalation — nothing else does."""

    severity: Literal["blocker", "likely_fine", "worth_knowing"]
    category: Literal[
        "missing", "expired", "format", "name_mismatch", "dob_mismatch", "field_gap"
    ]
    message: str
    evidence: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    needs_human: bool = False


class HumanDecision(BaseModel):
    """One resolution of one escalated Finding — the resume payload of the
    escalation interrupt (spec section 6.6/phase 6). Never batched: one
    HumanDecision answers exactly one Finding."""

    finding: Finding
    decision: Literal["accept", "override", "defer"]
    note: str | None = None
    decided_at: datetime = Field(default_factory=datetime.now)


class AuditResult(BaseModel):
    """One student's full run through the coordinator: what was required,
    what was found on their documents, and what came out of cross-checking
    the two. token_usage covers this run's verifier calls (the per-student
    marginal cost) — requirement extraction is scheme-level, shared across
    every student of that scheme, and tracked separately (see
    agents/coordinator.py). decision_log is the audit trail: who decided
    what, when, on what evidence, for every Finding that was escalated."""

    student_id: str
    scheme_id: str
    requirement: Requirement
    extracted_documents: list[ExtractedDocument] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    duration_seconds: float
    decision_log: list[HumanDecision] = Field(default_factory=list)
