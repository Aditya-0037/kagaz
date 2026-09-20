"""Requirement extractor: scheme notification -> Requirement (spec 6.1).

Input priority: PDF (primary, via pdfplumber) -> pasted text (secondary) ->
manual dict (last resort, no LLM at all). No URL fetching, no scraping.

Decomposed into four independent, separately-cacheable model calls — an 8B
local model reliably fills one small schema at a time, not one big one:
  1. document checklist
  2. required field labels
  3. format specs per document
  4. deadline
Each call is a Strands Agent using `structured_output_model=` (see
docs/sdk-notes.md — Agent.structured_output() is deprecated, this is the
current API). Every call goes through llm_cache.cached_call with a model
from model_provider.get_model(); nothing else touches either.

The four results are merged deterministically in Python (see _merge).
Whatever the model can't determine goes into Requirement.unresolved as
plain language — never a guessed value.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import TypeVar

import pdfplumber
from pydantic import BaseModel, Field
from strands import Agent

from contracts import Requirement, RequiredDoc
from llm_cache import cached_call
from model_provider import get_model, get_model_identifier
from tools.doc_types import normalize_doc_type
from tools.money import parse_inr

# Below this many characters, treat the input as unreadable (a blank/failed
# scan, a near-empty paste) and skip the LLM entirely rather than ask a
# model to hallucinate a checklist from noise. Comfortably above what a
# watermark-only page extracts to (~50 chars) and comfortably below either
# real scheme fixture (1148/2278 chars) — see scripts/generate_scheme_pdfs.py.
MIN_TEXT_LENGTH = 200

_OutputModelT = TypeVar("_OutputModelT", bound=BaseModel)


# --------------------------------------------------------------------------
# LLM-facing output models — one small schema per call
# --------------------------------------------------------------------------


class _ChecklistOutput(BaseModel):
    documents: list[str] = Field(
        default_factory=list,
        description="Every distinct required document label, worded as the source text words it.",
    )


class _FieldsOutput(BaseModel):
    fields: list[str] = Field(
        default_factory=list,
        description="Every application-form field label, worded exactly as the source text words it.",
    )


class _FormatSpecEntry(BaseModel):
    doc_type_label: str = Field(description="Which document this spec is for, matching a checklist label.")
    file_formats: list[str] = Field(default_factory=list, description="Accepted file extensions, e.g. ['jpg','jpeg']. Empty if not stated.")
    max_size_kb: int | None = Field(default=None, description="Maximum file size in KB. Null if not numerically stated.")
    width_px: int | None = Field(default=None, description="Required width in pixels. Null if not stated.")
    height_px: int | None = Field(default=None, description="Required height in pixels. Null if not stated.")
    unresolved_note: str | None = Field(
        default=None,
        description="Set this (and leave the numeric fields null) if the text only gives a vague, non-numeric statement for this document's format.",
    )


class _FormatSpecsOutput(BaseModel):
    specs: list[_FormatSpecEntry] = Field(default_factory=list)


class _DeadlineOutput(BaseModel):
    deadline_iso: str | None = Field(default=None, description="Application deadline as YYYY-MM-DD. Null if no fixed deadline is stated.")


class _EligibilityOutput(BaseModel):
    max_family_income: str | None = Field(
        default=None,
        description=(
            "The maximum family/parental annual income allowed, copied as the text writes it "
            "(e.g. 'Rs. 2,50,000 per annum', '2.5 lakh'). Null if the text states no income ceiling."
        ),
    )
    criteria: list[str] = Field(
        default_factory=list,
        description=(
            "Every other stated eligibility rule, one short plain-language sentence each "
            "(course/class, category, state of domicile, minimum marks, age). Empty if none stated."
        ),
    )


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------


def _note_block(note: str | None) -> str:
    """The applicant's own instruction, if they gave one.

    Placed before the source text and clearly labelled as guidance from
    the person, not as part of the notification — so it can steer what to
    look for ("this is for the SC category", "I only care about the photo
    rules") without being mistaken for a scheme rule.
    """
    note = (note or "").strip()
    if not note:
        return ""
    return (
        "\n\nTHE APPLICANT ASKED YOU TO PAY ATTENTION TO THIS (their words, "
        "not part of the notification — use it to decide what matters, never "
        "as a source of facts):\n"
        f"{note}\n\n"
    )


def _checklist_prompt(text: str, note: str | None = None) -> str:
    return (
        "You are extracting a document checklist from an Indian government scheme "
        "notification. Read the ENTIRE text below and list every distinct supporting "
        "document type applicants must submit (physical documents/certificates only "
        "— do NOT include application-form fields like 'Name' or 'Date of Birth'). "
        "Use short labels matching how the text names them (e.g. 'Income Certificate', "
        "'Marksheet'). Include a document even if it sounds optional or conditional.\n\n"
        f"{_note_block(note)}SCHEME NOTIFICATION TEXT:\n{text}"
    )


def _fields_prompt(text: str, note: str | None = None) -> str:
    return (
        "You are extracting application-form field labels from an Indian government "
        "scheme notification. Read the ENTIRE text below and list every particular the "
        "online application form asks the applicant to fill in (e.g. 'Full Name', "
        "'Date of Birth', 'Bank Account Number'). Word each label exactly as the text "
        "words it. Do NOT include document names.\n\n"
        f"{_note_block(note)}SCHEME NOTIFICATION TEXT:\n{text}"
    )


def _format_specs_prompt(text: str, note: str | None = None) -> str:
    return (
        "You are extracting file-format specifications for uploaded documents from an "
        "Indian government scheme notification. Format specifications are sometimes "
        "given in a separate table or annexure elsewhere in the document, not "
        "necessarily next to the document list — search the ENTIRE text below. For "
        "every document you find a specification for, record its accepted file "
        "formats, maximum file size in KB, and pixel dimensions if given.\n\n"
        "If the text only gives a vague statement for a document (e.g. 'in the "
        "prescribed format' with no actual numbers), do NOT invent numbers — leave "
        "file_formats empty and max_size_kb/width_px/height_px null, and instead put a "
        "short quote or paraphrase of what the text actually says into "
        "unresolved_note.\n\n"
        f"{_note_block(note)}SCHEME NOTIFICATION TEXT:\n{text}"
    )


def _deadline_prompt(text: str, note: str | None = None) -> str:
    return (
        "You are extracting the application deadline from an Indian government scheme "
        "notification. Read the ENTIRE text below and find the last date for "
        "submission of applications. Return it as deadline_iso in YYYY-MM-DD format. "
        "If no fixed deadline is stated anywhere in the text, return null for "
        "deadline_iso — do not guess or invent a date.\n\n"
        f"{_note_block(note)}SCHEME NOTIFICATION TEXT:\n{text}"
    )


def _eligibility_prompt(text: str, note: str | None = None) -> str:
    return (
        "You are extracting WHO IS ELIGIBLE from the application form or notification "
        "below — not what documents are needed. It may be any kind of form: a "
        "scholarship, a subsidy or welfare scheme, an admission form, a job or exam "
        "application. Read the ENTIRE text and take every rule from THIS text only.\n\n"
        "1. max_family_income: if this form states a maximum family/parental/household/"
        "applicant annual income to qualify, copy that amount exactly as written (keep "
        "the currency symbol, commas, and any 'lakh'/'per annum' wording). If this form "
        "states no income ceiling, return null — never carry over a figure from another "
        "scheme and never invent one.\n"
        "2. criteria: every OTHER stated eligibility rule, as short plain sentences — "
        "whatever this particular form actually requires (course or class of study, "
        "caste/category, state of domicile, minimum marks, age limits, employment "
        "status, land holding, residence). Do not include document requirements or file "
        "format rules here. Empty list if the text states none.\n\n"
        f"{_note_block(note)}FORM / NOTIFICATION TEXT:\n{text}"
    )


# --------------------------------------------------------------------------
# Model call plumbing
# --------------------------------------------------------------------------


def _run_structured(
    prompt: str,
    output_model: type[_OutputModelT],
    *,
    scheme_id: str,
    call_name: str,
    llm_mode: str | None = None,
) -> _OutputModelT:
    provider = os.environ.get("KAGAZ_MODEL_PROVIDER", "vertex")
    model_name = get_model_identifier(provider)

    def call_fn():
        agent = Agent(model=get_model(provider))
        result = agent(prompt, structured_output_model=output_model)
        return result.structured_output.model_dump(mode="json")

    inputs = {"scheme_id": scheme_id, "call": call_name}
    response = cached_call(provider, model_name, prompt, inputs, call_fn, mode=llm_mode)
    return output_model.model_validate(response)


def _parse_iso_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Merge (deterministic, pure Python)
# --------------------------------------------------------------------------


def _merge(
    scheme_id: str,
    scheme_name: str,
    source: str,
    checklist: _ChecklistOutput,
    fields_out: _FieldsOutput,
    format_specs_out: _FormatSpecsOutput,
    deadline_out: _DeadlineOutput,
    eligibility_out: _EligibilityOutput | None = None,
) -> Requirement:
    unresolved: list[str] = []

    doc_types: list[str] = []
    seen: set[str] = set()
    for label in checklist.documents:
        canon = normalize_doc_type(label)
        if canon not in seen:
            seen.add(canon)
            doc_types.append(canon)

    specs_by_type: dict[str, _FormatSpecEntry] = {}
    for entry in format_specs_out.specs:
        specs_by_type[normalize_doc_type(entry.doc_type_label)] = entry

    required_documents: list[RequiredDoc] = []
    for doc_type in doc_types:
        spec = specs_by_type.get(doc_type)
        file_formats: list[str] = []
        max_size_kb: int | None = None
        dimensions_px: tuple[int, int] | None = None

        if spec is None:
            unresolved.append(f"No format specification found for {doc_type}.")
        else:
            file_formats = [f.lower().lstrip(".") for f in spec.file_formats]
            max_size_kb = spec.max_size_kb
            if spec.width_px and spec.height_px:
                dimensions_px = (spec.width_px, spec.height_px)
            if spec.unresolved_note:
                unresolved.append(f"{doc_type}: {spec.unresolved_note}")
            elif not file_formats and max_size_kb is None and dimensions_px is None:
                unresolved.append(f"No concrete format specification stated for {doc_type}.")

        required_documents.append(
            RequiredDoc(
                doc_type=doc_type,
                file_formats=file_formats,
                max_size_kb=max_size_kb,
                dimensions_px=dimensions_px,
                must_be_valid_on=None,
                notes=None,
            )
        )

    # Reconcile the two calls. The checklist call reads prose; the
    # format-specs call reads the size/format table. A document named only
    # in prose is easy for the checklist call to miss — "Photograph" and
    # "Specimen Signature" were both dropped that way — while the table
    # lists them with exact numbers. A doc_type the specs call gave
    # concrete numbers for is required, whatever the checklist said, so
    # take the union rather than silently losing it.
    for doc_type, spec in specs_by_type.items():
        if doc_type in seen:
            continue
        has_numbers = bool(spec.file_formats) or spec.max_size_kb is not None or (
            spec.width_px and spec.height_px
        )
        if not has_numbers:
            continue
        seen.add(doc_type)
        doc_types.append(doc_type)
        required_documents.append(
            RequiredDoc(
                doc_type=doc_type,
                file_formats=[f.lower().lstrip(".") for f in spec.file_formats],
                max_size_kb=spec.max_size_kb,
                dimensions_px=(spec.width_px, spec.height_px) if spec.width_px and spec.height_px else None,
                must_be_valid_on=None,
                notes=None,
            )
        )
        unresolved.append(
            f"{doc_type} appears in this form's format/size table but not in its document list — "
            "included because the table states real requirements for it. Confirm it's needed."
        )

    deadline: date | None = None
    if deadline_out.deadline_iso:
        deadline = _parse_iso_date(deadline_out.deadline_iso)
        if deadline is None:
            unresolved.append(f"Deadline text {deadline_out.deadline_iso!r} could not be parsed as a date.")
    else:
        unresolved.append("No application deadline could be determined from the notification text.")

    required_fields = list(dict.fromkeys(fields_out.fields))  # dedupe, preserve order

    total_checks = 2 + len(required_documents)
    resolved_checks = (
        (1 if deadline is not None else 0)
        + (1 if required_fields else 0)
        + sum(1 for rd in required_documents if rd.file_formats or rd.max_size_kb or rd.dimensions_px)
    )
    confidence = round(resolved_checks / total_checks, 2) if total_checks else 0.0

    max_income = parse_inr(eligibility_out.max_family_income) if eligibility_out else None
    if eligibility_out and eligibility_out.max_family_income and max_income is None:
        unresolved.append(
            f"Family income limit stated as {eligibility_out.max_family_income!r}, which could not be "
            "read as a rupee amount — check it against your income certificate yourself."
        )

    return Requirement(
        scheme_id=scheme_id,
        scheme_name=scheme_name,
        deadline=deadline,
        required_documents=required_documents,
        required_fields=required_fields,
        source=source,
        confidence=confidence,
        unresolved=unresolved,
        max_family_income_inr=max_income,
        eligibility_criteria=list(eligibility_out.criteria) if eligibility_out else [],
    )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def extract_pdf_text(pdf_path: Path | str) -> str:
    """Public: raw text out of a PDF, no LLM. Reused by
    agents/scheme_input.py for a scheme PDF fetched from a URL or uploaded
    directly, so both paths share exactly one PDF-reading implementation."""
    with pdfplumber.open(Path(pdf_path)) as pdf:
        pages_text = [page.extract_text() or "" for page in pdf.pages]
    return "\n\n".join(pages_text).strip()


_extract_pdf_text = extract_pdf_text


def _extract_requirement_from_text(
    text: str, scheme_id: str, scheme_name: str, source: str, llm_mode: str | None = None,
    note: str | None = None,
) -> Requirement:
    text = text.strip()
    if len(text) < MIN_TEXT_LENGTH:
        return Requirement(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            deadline=None,
            required_documents=[],
            required_fields=[],
            source=source,
            confidence=0.0,
            unresolved=["Could not extract readable text from the input; it appears empty, blank, or unreadable."],
        )

    checklist = _run_structured(
        _checklist_prompt(text, note), _ChecklistOutput, scheme_id=scheme_id, call_name="checklist", llm_mode=llm_mode
    )
    fields_out = _run_structured(
        _fields_prompt(text, note), _FieldsOutput, scheme_id=scheme_id, call_name="fields", llm_mode=llm_mode
    )
    format_specs_out = _run_structured(
        _format_specs_prompt(text, note), _FormatSpecsOutput, scheme_id=scheme_id, call_name="format_specs", llm_mode=llm_mode
    )
    deadline_out = _run_structured(
        _deadline_prompt(text, note), _DeadlineOutput, scheme_id=scheme_id, call_name="deadline", llm_mode=llm_mode
    )
    eligibility_out = _run_structured(
        _eligibility_prompt(text, note), _EligibilityOutput, scheme_id=scheme_id, call_name="eligibility", llm_mode=llm_mode
    )

    return _merge(
        scheme_id, scheme_name, source, checklist, fields_out, format_specs_out, deadline_out, eligibility_out
    )


def extract_requirement_from_pdf(
    pdf_path: Path | str, scheme_id: str, scheme_name: str, llm_mode: str | None = None
) -> Requirement:
    text = _extract_pdf_text(Path(pdf_path))
    return _extract_requirement_from_text(text, scheme_id, scheme_name, source="pdf", llm_mode=llm_mode)


def extract_requirement_from_text(
    text: str, scheme_id: str, scheme_name: str, source: str = "text", llm_mode: str | None = None,
    note: str | None = None,
) -> Requirement:
    """Public entry point for the real-account flow's non-PDF scheme-input
    tiers (agents/scheme_input.py) — pasted text, a URL's fetched text/HTML,
    or OCR'd screenshot text all land here, tagged with the source they
    actually came from. llm_mode is forced to "live" by the real-account
    flow regardless of the server-wide KAGAZ_LLM_MODE, so real scheme text
    is never written into the committed replay cache."""
    return _extract_requirement_from_text(text, scheme_id, scheme_name, source=source, llm_mode=llm_mode, note=note)


def build_manual_requirement(
    scheme_id: str,
    scheme_name: str,
    *,
    deadline: date | None = None,
    required_documents: list[RequiredDoc] | None = None,
    required_fields: list[str] | None = None,
) -> Requirement:
    """Last-resort tier: a human supplies the Requirement directly, no LLM
    involved. Trusted as given — confidence=1.0, nothing unresolved."""
    return Requirement(
        scheme_id=scheme_id,
        scheme_name=scheme_name,
        deadline=deadline,
        required_documents=required_documents or [],
        required_fields=required_fields or [],
        source="manual",
        confidence=1.0,
        unresolved=[],
    )
