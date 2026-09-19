"""FastAPI web UI (phase 8b) — a demo surface, not the product.

Server-rendered HTML, no React, no build step. Four screens: pick student
and scheme -> run with live progress -> escalation (blocks until a
decision is submitted) -> results with findings by severity and a
download button. See web/templates/run.html for all four — status drives
which one renders.
"""

from __future__ import annotations

import io
import os
import zipfile

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware

from api.app_routes import router as app_router
from api.auth_routes import router as auth_router
from api.run_state import RUNS, SCHEMES, start_run, submit_decision
from api.templates import templates
from auth import NotAuthenticated
from fixtures_loader import list_students

app = FastAPI(title="Kagaz")

# KAGAZ_SESSION_SECRET must be set in production (deployment fails loudly
# without it there); a fixed dev-only default keeps local runs and tests
# frictionless, since this cookie only ever holds a random user id, never
# anything sensitive by itself.
_session_secret = os.environ.get("KAGAZ_SESSION_SECRET")
if _session_secret is None:
    if os.environ.get("KAGAZ_ENV") == "production":
        raise RuntimeError("KAGAZ_SESSION_SECRET must be set in production")
    _session_secret = "dev-only-insecure-secret-do-not-use-in-production"
app.add_middleware(SessionMiddleware, secret_key=_session_secret)


@app.exception_handler(NotAuthenticated)
def _not_authenticated(request: Request, exc: NotAuthenticated) -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


app.include_router(auth_router)
app.include_router(app_router)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"students": list_students(), "schemes": {k: v[1] for k, v in SCHEMES.items()}},
    )


@app.post("/run")
def create_run(student_id: str = Form(...), scheme_id: str = Form(...)) -> RedirectResponse:
    if scheme_id not in SCHEMES:
        raise HTTPException(400, f"unknown scheme_id {scheme_id!r}")
    state = start_run(student_id, scheme_id)
    return RedirectResponse(f"/run/{state.run_id}", status_code=303)


@app.get("/run/{run_id}", response_class=HTMLResponse)
def run_status(request: Request, run_id: str) -> HTMLResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(404, "run not found")
    return templates.TemplateResponse(request, "run.html", {"state": state})


@app.post("/run/{run_id}/decide")
def decide(run_id: str, decision: str = Form(...), note: str = Form("")) -> RedirectResponse:
    if RUNS.get(run_id) is None:
        raise HTTPException(404, "run not found")
    try:
        submit_decision(run_id, decision, note or None)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/run/{run_id}", status_code=303)


@app.get("/run/{run_id}/download")
def download(run_id: str) -> StreamingResponse:
    state = RUNS.get(run_id)
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
