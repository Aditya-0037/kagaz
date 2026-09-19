"""Real-user /app routes: dashboard, new application, upload, run, decide, download.

Phase A/B stub — just the authenticated dashboard for now, enough for the
signup/login flow to redirect somewhere real and for require_user to be
exercised end to end. Phases C-F add scheme input, uploads, and the run
pipeline here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import db
from api.templates import templates
from auth import require_user

router = APIRouter()


@router.get("/app", response_class=HTMLResponse)
def dashboard(request: Request, user_id: str = Depends(require_user)) -> HTMLResponse:
    user = db.get_user(user_id)
    runs = db.list_runs_for_user(user_id)
    return templates.TemplateResponse(request, "app_dashboard.html", {"user": user, "runs": runs})
