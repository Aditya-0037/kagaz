"""Real-user /app routes: the digital locker, multi-source scheme input,
document matching, and the run pipeline — everything the synthetic demo
(api/main.py) does, but against a real account's own documents.

Flow: /app (dashboard) -> /app/new (paste/URL/PDF/screenshot scheme input,
extracted live) -> /app/runs/{id}/match (map each required document to a
locker item, uploading new ones on the spot) -> /app/runs/{id} (status,
escalation, results with the verified/can't-verify split) ->
/app/runs/{id}/download. /app/documents is the locker on its own: upload,
view expiry status, delete — independent of any particular application.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

import blob_storage
import db
from agents.scheme_input import UnsafeURLError, fetch_url_text, from_pasted_text, from_pdf_upload, from_screenshot
from agents.requirement_extractor import extract_requirement_from_text
from api import real_run_state
from api.templates import templates
from auth import require_user
from contracts import Requirement
from tools.doc_types import CANONICAL_DOC_TYPES
from tools.packager import NON_DOCUMENT_REJECTION_CAUSES

router = APIRouter()

DOC_TYPE_LABELS: dict[str, str] = {
    "income_certificate": "Income Certificate",
    "caste_certificate": "Caste Certificate",
    "domicile_certificate": "Domicile / Residence Certificate",
    "marksheet": "Marksheet",
    "bank_passbook": "Bank Passbook",
    "photo": "Photograph",
    "signature": "Signature",
}

SCRATCH_DIR = Path(__file__).parent.parent / "outbox" / "real_scratch"
EXPIRY_SOON_DAYS = 30

# What the verification pipeline can actually read: images go through OCR
# or the vision backend, PDFs through pdfplumber's text layer. Anything
# else (a .docx, a .txt renamed from something, a zip) would only fail
# later, mid-run — reject it at the door with a clear message instead.
ACCEPTED_DOC_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}


def _reject_reason(upload: UploadFile) -> str | None:
    name = (upload.filename or "").strip()
    if not name:
        return "No file was chosen."
    if Path(name).suffix.lower() not in ACCEPTED_DOC_SUFFIXES:
        return (
            f"{name} isn't a file Kagaz can read. Upload a photo or scan "
            "(JPG, PNG) or a PDF of the document."
        )
    return None


def _expiry_status(expiry_date: str | None) -> str:
    """"expired" / "soon" / "ok" / "none" — drives the locker's pill color."""
    if not expiry_date:
        return "none"
    try:
        d = date.fromisoformat(expiry_date)
    except ValueError:
        return "none"
    today = date.today()
    if d < today:
        return "expired"
    if (d - today).days <= EXPIRY_SOON_DAYS:
        return "soon"
    return "ok"


def _renewal_note(expiry_date: str | None) -> str | None:
    """The actual instruction a user needs, not just a date: apply for a
    replacement now, or start the renewal before the document lapses."""
    if not expiry_date:
        return None
    try:
        d = date.fromisoformat(expiry_date)
    except ValueError:
        return None
    days = (d - date.today()).days
    if days < 0:
        return f"Expired {abs(days)} day(s) ago — apply for a new one before using it on any form."
    if days == 0:
        return "Expires today — apply for a new one now."
    if days <= EXPIRY_SOON_DAYS:
        return f"Expires in {days} day(s) — start the renewal now; these usually take a few weeks to issue."
    return None


def _own_run_or_404(run_id: str, user_id: str) -> dict:
    run = db.get_run(run_id)
    if run is None or run.get("user_id") != user_id:
        # 404, not 403 — don't reveal whether a run_id exists to a non-owner.
        raise HTTPException(404, "run not found")
    return run


def _save_upload(user_id: str, doc_type: str, label: str, upload: UploadFile, expiry_date: str | None) -> str:
    """Save one uploaded file into GCS + the Firestore locker, return the
    new document_id."""
    content = upload.file.read()
    blob_path = f"users/{user_id}/documents/{uuid.uuid4().hex}_{upload.filename or doc_type}"
    gcs_uri = blob_storage.upload_bytes(content, blob_path, content_type=upload.content_type)
    return db.create_document(
        user_id=user_id,
        doc_type=doc_type,
        label=label or DOC_TYPE_LABELS.get(doc_type, doc_type),
        filename=upload.filename or doc_type,
        content_type=upload.content_type or "application/octet-stream",
        gcs_uri=gcs_uri,
        expiry_date=expiry_date or None,
    )


# ------------------------------------------------------------- dashboard --


@router.get("/app", response_class=HTMLResponse)
def dashboard(request: Request, user_id: str = Depends(require_user)) -> HTMLResponse:
    user = db.get_user(user_id)
    documents = db.list_documents_for_user(user_id)
    runs = db.list_runs_for_user(user_id)

    expiring = [d for d in documents if _expiry_status(d.get("expiry_date")) in ("expired", "soon")]

    return templates.TemplateResponse(
        request,
        "app_dashboard.html",
        {
            "user": user,
            "document_count": len(documents),
            "expiring": expiring,
            "expiry_status": _expiry_status,
            "renewal_note": _renewal_note,
            "runs": runs[:8],
            "doc_type_labels": DOC_TYPE_LABELS,
        },
    )


# ----------------------------------------------------------------- locker --


@router.get("/app/documents", response_class=HTMLResponse)
def locker(request: Request, error: str | None = None, user_id: str = Depends(require_user)) -> HTMLResponse:
    documents = db.list_documents_for_user(user_id)
    return templates.TemplateResponse(
        request,
        "app_locker.html",
        {
            "documents": documents,
            "expiry_status": _expiry_status,
            "renewal_note": _renewal_note,
            "doc_types": sorted(CANONICAL_DOC_TYPES),
            "doc_type_labels": DOC_TYPE_LABELS,
            "error": error,
        },
    )


@router.post("/app/documents")
def upload_document(
    doc_type: str = Form(...),
    label: str = Form(""),
    expiry_date: str = Form(""),
    file: UploadFile = File(...),
    user_id: str = Depends(require_user),
) -> RedirectResponse:
    if doc_type not in CANONICAL_DOC_TYPES:
        raise HTTPException(400, f"unknown doc_type {doc_type!r}")
    reason = _reject_reason(file)
    if reason:
        return RedirectResponse(f"/app/documents?error={quote(reason)}", status_code=303)
    _save_upload(user_id, doc_type, label, file, expiry_date)
    return RedirectResponse("/app/documents", status_code=303)


@router.post("/app/documents/{document_id}/delete")
def delete_document(document_id: str, user_id: str = Depends(require_user)) -> RedirectResponse:
    document = db.get_document(document_id)
    if document is not None and document.get("user_id") == user_id:
        db.delete_document(document_id)
    return RedirectResponse("/app/documents", status_code=303)


# ----------------------------------------------------- new application --


@router.get("/app/new", response_class=HTMLResponse)
def new_application(request: Request, user_id: str = Depends(require_user)) -> HTMLResponse:
    return templates.TemplateResponse(request, "app_new.html", {"error": None})


@router.post("/app/new", response_model=None)
def create_application(
    request: Request,
    tier: str = Form(...),
    scheme_name: str = Form(""),
    text: str = Form(""),
    url: str = Form(""),
    pdf_file: UploadFile | None = File(None),
    screenshot_file: UploadFile | None = File(None),
    user_id: str = Depends(require_user),
) -> HTMLResponse | RedirectResponse:
    run_id = uuid.uuid4().hex[:12]
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if tier == "paste":
            scheme_text, source = from_pasted_text(text), "text"
        elif tier == "url":
            fetched = fetch_url_text(url.strip())
            scheme_text, source = fetched.text, fetched.source
        elif tier == "pdf":
            if pdf_file is None or not pdf_file.filename:
                raise ValueError("choose a PDF file to upload")
            tmp_path = SCRATCH_DIR / f"{run_id}.pdf"
            tmp_path.write_bytes(pdf_file.file.read())
            try:
                scheme_text = from_pdf_upload(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)
            source = "pdf"
        elif tier == "screenshot":
            if screenshot_file is None or not screenshot_file.filename:
                raise ValueError("choose a screenshot image to upload")
            suffix = Path(screenshot_file.filename).suffix or ".jpg"
            tmp_path = SCRATCH_DIR / f"{run_id}{suffix}"
            tmp_path.write_bytes(screenshot_file.file.read())
            try:
                scheme_text = from_screenshot(tmp_path, cache_dir=SCRATCH_DIR / "ocr_cache", llm_mode="live")
            finally:
                tmp_path.unlink(missing_ok=True)
            source = "screenshot"
        else:
            raise ValueError(f"unknown input tier {tier!r}")
    except (UnsafeURLError, ValueError) as exc:
        return templates.TemplateResponse(request, "app_new.html", {"error": str(exc)}, status_code=400)

    display_name = scheme_name.strip() or "My application"
    requirement = extract_requirement_from_text(scheme_text, run_id, display_name, source=source, llm_mode="live")

    if not requirement.required_documents and requirement.unresolved:
        return templates.TemplateResponse(
            request,
            "app_new.html",
            {"error": "Couldn't extract a document checklist from that input: " + "; ".join(requirement.unresolved)},
            status_code=400,
        )

    # Not db.create_run() — that generates its own random id, and this
    # route already minted run_id above (used for scratch file names and
    # the redirect URL). update_run's set(merge=True) creates the document
    # if it doesn't exist yet, so this is the create.
    db.update_run(
        run_id,
        user_id=user_id,
        status="draft",
        scheme_source=display_name,
        input_tier=tier,
        requirement=requirement.model_dump(mode="json"),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    return RedirectResponse(f"/app/runs/{run_id}/match", status_code=303)


# ------------------------------------------------------------ matching --


@router.get("/app/runs/{run_id}/match", response_class=HTMLResponse)
def match_documents(request: Request, run_id: str, user_id: str = Depends(require_user)) -> HTMLResponse:
    run = _own_run_or_404(run_id, user_id)
    requirement = Requirement.model_validate(run["requirement"])
    documents = db.list_documents_for_user(user_id)

    by_type: dict[str, list[dict]] = {}
    for doc in documents:
        by_type.setdefault(doc["doc_type"], []).append(doc)

    return templates.TemplateResponse(
        request,
        "app_match.html",
        {
            "run": run,
            "run_id": run_id,
            "requirement": requirement,
            "locker_by_type": by_type,
            "doc_type_labels": DOC_TYPE_LABELS,
        },
    )


@router.post("/app/runs/{run_id}/match", response_model=None)
async def start_matched_run(
    request: Request, run_id: str, user_id: str = Depends(require_user)
) -> HTMLResponse | RedirectResponse:
    run = _own_run_or_404(run_id, user_id)
    requirement = Requirement.model_validate(run["requirement"])
    form = await request.form()

    gcs_uris: dict[str, str] = {}
    for required in requirement.required_documents:
        doc_type = required.doc_type
        choice = form.get(f"choice_{doc_type}")
        if not choice or choice == "none":
            continue
        if choice == "upload":
            upload = form.get(f"file_{doc_type}")
            if upload is None or not getattr(upload, "filename", None):
                continue
            if _reject_reason(upload):
                # Skipped rather than failed: the run still proceeds and
                # reports this document as missing, which is the truth.
                continue
            expiry = form.get(f"expiry_{doc_type}", "")
            document_id = _save_upload(user_id, doc_type, "", upload, expiry)
        else:
            document_id = choice
        document = db.get_document(document_id)
        if document is not None and document.get("user_id") == user_id:
            gcs_uris[doc_type] = document["gcs_uri"]

    real_run_state.start_run(run_id, user_id, requirement, gcs_uris)
    return RedirectResponse(f"/app/runs/{run_id}", status_code=303)


# ------------------------------------------------------------------ run --


@router.get("/app/runs/{run_id}", response_class=HTMLResponse)
def run_status(request: Request, run_id: str, user_id: str = Depends(require_user)) -> HTMLResponse:
    run = _own_run_or_404(run_id, user_id)
    state = real_run_state.RUNS.get(run_id)
    return templates.TemplateResponse(
        request,
        "app_run.html",
        {
            "run": run,
            "run_id": run_id,
            "state": state,
            "non_document_causes": NON_DOCUMENT_REJECTION_CAUSES,
        },
    )


@router.post("/app/runs/{run_id}/decide")
def decide(run_id: str, decision: str = Form(...), note: str = Form(""), user_id: str = Depends(require_user)) -> RedirectResponse:
    _own_run_or_404(run_id, user_id)
    try:
        real_run_state.submit_decision(run_id, decision, note or None)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/app/runs/{run_id}", status_code=303)


@router.get("/app/runs/{run_id}/download")
def download(run_id: str, user_id: str = Depends(require_user)) -> StreamingResponse:
    _own_run_or_404(run_id, user_id)
    state = real_run_state.RUNS.get(run_id)
    if state is None or state.package_dir is None:
        raise HTTPException(404, "package not ready yet")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in state.package_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(state.package_dir.parent))
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{state.package_dir.name}.zip"'},
    )
