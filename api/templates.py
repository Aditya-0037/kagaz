"""The single Jinja2Templates instance shared by every router.

Kept separate so api/main.py, api/auth_routes.py, and api/app_routes.py
all see the same env globals (kagaz_llm_mode etc.) without duplicating
registration or risking one router's templates falling out of sync.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.templating import Jinja2Templates

from tools.money import format_inr

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))
# Evaluated per-render (not at import time) so a deployed instance's env
# var is always reflected, and tests that monkeypatch it mid-session see
# the change too.
templates.env.globals["kagaz_llm_mode"] = lambda: os.environ.get("KAGAZ_LLM_MODE", "replay")
# The nav in base.html needs to know "is someone logged in" on every page
# — demo pages included — without every route handler fetching the user.
# Starlette's TemplateResponse(request, ...) already puts `request` in
# every template's context, so the nav just calls this with it.
templates.env.globals["is_logged_in"] = lambda request: bool(request.session.get("user_id"))
# Rupee amounts render with Indian digit grouping (2,50,000) wherever a
# template shows a form's income ceiling.
templates.env.globals["format_inr"] = format_inr
