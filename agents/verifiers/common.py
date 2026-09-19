"""Shared machinery for the five certificate-style verifiers.

Each doc-type module (income_certificate.py, caste_certificate.py, ...) is
its own Strands agent — its own prompt and its own view onto which fields
matter for that document — but they share one LLM-facing output schema
(every possible field, all optional) and one runner. That's an
implementation convenience, not a shortcut: an 8B model handling "extract
whatever's relevant to this document type" from one shared schema is a much
easier task than any doc type ever needing to guess at another's fields,
since each module's prompt only ever asks about its own doc type's fields.

extraction_confidence is computed deterministically in Python (fraction of
that doc type's expected fields that came back non-None), not self-reported
by the model — small local models are unreliable at calibrating their own
confidence, same reasoning as agents/requirement_extractor.py's confidence
scoring. A field the model could not read is absent from
ExtractedDocument.fields entirely, never guessed.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from pydantic import BaseModel
from strands import Agent

from contracts import ExtractedDocument
from llm_cache import cached_call
from model_provider import get_model, get_model_identifier
from tools.dates import parse_date_flexible


class VerifierOutput(BaseModel):
    """Every field any of the five verifiers might ask about. All optional
    — a given doc type's prompt only asks about the subset relevant to it,
    and _run_verifier only reads back that subset (see expected_fields)."""

    name: str | None = None
    father_name: str | None = None
    dob: str | None = None
    issue_date: str | None = None
    valid_until: str | None = None
    certificate_no: str | None = None
    annual_income: str | None = None
    caste_category: str | None = None
    roll_no: str | None = None
    marks_percent: str | None = None
    account_no: str | None = None
    bank_name: str | None = None


# Fields that map onto ExtractedDocument.issue_date/.valid_until directly
# rather than into the .fields dict.
_DATE_FIELDS = {"issue_date", "valid_until"}


def run_verifier(
    doc_type: str,
    prompt: str,
    expected_fields: set[str],
    source_path: Path,
    *,
    cache_inputs: dict,
    llm_mode: str | None = None,
) -> tuple[ExtractedDocument, dict]:
    """Run one verifier call and return (ExtractedDocument, token_usage).

    expected_fields defines both what this doc type's prompt should be
    asking about (used for the confidence computation) and which of
    VerifierOutput's fields land in ExtractedDocument.fields.
    """
    provider = os.environ.get("KAGAZ_MODEL_PROVIDER", "vertex")
    model_name = get_model_identifier(provider)

    def call_fn():
        # A small local model occasionally fumbles the structured-output
        # tool call (emits malformed/duplicated JSON) — retry a couple of
        # times before giving up. Only runs in record/live mode; replay
        # never calls this at all, so this never touches the network in
        # tests/CI.
        last_error: Exception | None = None
        for _attempt in range(3):
            try:
                agent = Agent(model=get_model(provider))
                result = agent(prompt, structured_output_model=VerifierOutput)
                usage = dict(getattr(result.metrics, "accumulated_usage", None) or {})
                return {"output": result.structured_output.model_dump(mode="json"), "usage": usage}
            except Exception as exc:  # noqa: BLE001 - genuinely provider/parse-agnostic retry
                last_error = exc
        raise last_error

    response = cached_call(provider, model_name, prompt, cache_inputs, call_fn, mode=llm_mode)
    output = VerifierOutput.model_validate(response["output"])
    usage = response.get("usage", {})

    fields: dict[str, str] = {}
    filled = 0
    for field_name in expected_fields:
        if field_name in _DATE_FIELDS:
            continue
        value = getattr(output, field_name, None)
        if value is not None and str(value).strip():
            fields[field_name] = str(value).strip()
            filled += 1

    issue_date: date | None = None
    valid_until: date | None = None
    if "issue_date" in expected_fields:
        if output.issue_date:
            issue_date = parse_date_flexible(output.issue_date)
            if issue_date is not None:
                filled += 1
        # issue_date being absent doesn't count against confidence as
        # heavily as a missing name/dob would in principle, but it's still
        # one of the doc type's expected fields, so an absence does count.
    if "valid_until" in expected_fields:
        if output.valid_until:
            valid_until = parse_date_flexible(output.valid_until)
            if valid_until is not None:
                filled += 1

    confidence = round(filled / len(expected_fields), 2) if expected_fields else 0.0

    document = ExtractedDocument(
        doc_type=doc_type,
        source_path=source_path,
        fields=fields,
        issue_date=issue_date,
        valid_until=valid_until,
        extraction_confidence=confidence,
    )
    return document, usage
