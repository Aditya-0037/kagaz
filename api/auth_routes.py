"""Signup / login / logout for the real-user /app flow.

Separate from the synthetic demo (api/main.py) entirely — this is the only
place a password is ever handled, always hashed via auth.hash_password
before it reaches db.py, never stored or logged in plaintext.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import db
from api.templates import templates
from auth import hash_password, log_in, log_out, verify_password

router = APIRouter()


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "signup.html", {"error": None})


@router.post("/signup", response_model=None)
def signup(request: Request, email: str = Form(...), password: str = Form(...)) -> HTMLResponse | RedirectResponse:
    email = email.strip().lower()
    if not email or "@" not in email:
        return templates.TemplateResponse(request, "signup.html", {"error": "Enter a valid email address."})
    if len(password) < 8:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "Password must be at least 8 characters."}
        )
    try:
        user_id = db.create_user(email, hash_password(password))
    except ValueError as exc:
        return templates.TemplateResponse(request, "signup.html", {"error": str(exc)})
    log_in(request, user_id)
    return RedirectResponse("/app", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_model=None)
def login(request: Request, email: str = Form(...), password: str = Form(...)) -> HTMLResponse | RedirectResponse:
    user = db.get_user_by_email(email)
    if user is None or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(request, "login.html", {"error": "Incorrect email or password."})
    log_in(request, user["id"])
    return RedirectResponse("/app", status_code=303)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    log_out(request)
    return RedirectResponse("/", status_code=303)
