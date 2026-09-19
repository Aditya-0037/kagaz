"""Scheme input tiers for the real-account flow: paste text, upload a PDF
or screenshot, or paste a URL. Every tier ends up as plain text (or a PDF
path) feeding the same `extract_requirement_from_text`/
`extract_requirement_from_pdf` the demo flow already uses — this module's
only job is getting text out of whatever the user handed it.

Never a login, never a crawl. fetch_url_text does exactly one GET of a
URL a human pasted in, with SSRF guards: only http/https, the resolved IP
must not be private/loopback/link-local/multicast, no redirect is
followed, and both the request and the response body are capped.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from agents.requirement_extractor import extract_pdf_text
from tools.ocr import extract_text as ocr_extract_text

_REQUEST_TIMEOUT_SECONDS = 15
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB — a scheme notice is text/PDF, never larger
_USER_AGENT = "Kagaz/1.0 (+single-page fetch for a user-pasted scheme URL; no crawling)"


class UnsafeURLError(ValueError):
    """Raised by fetch_url_text when a URL fails the SSRF guard."""


@dataclass
class FetchedScheme:
    text: str
    source: str  # "url" (HTML) or "pdf" (PDF fetched from a URL)


def from_pasted_text(text: str) -> str:
    """Tier 1: the user pasted the scheme's text directly. No transformation."""
    return text.strip()


def from_pdf_upload(pdf_path: Path | str) -> str:
    """Tier 2: the user uploaded the scheme notification as a PDF."""
    return extract_pdf_text(pdf_path)


def from_screenshot(image_path: Path | str, *, cache_dir: Path, llm_mode: str = "live") -> str:
    """Tier 3: the user uploaded a screenshot of the scheme notification.
    Reuses the vision OCR backend — the same one that reads document
    images — pointed at a real-user scratch cache_dir, never
    fixtures/ocr_cache/, and forced live so nothing real is cached."""
    return ocr_extract_text(image_path, cache_dir=cache_dir, llm_mode=llm_mode)


def _assert_safe_url(url: str) -> str:
    """Raise UnsafeURLError unless url is a plain http(s) URL whose host
    resolves to a public, routable address. Returns the hostname."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"only http/https URLs are allowed, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"could not resolve host {parsed.hostname!r}") from exc

    for family, _type, _proto, _canon, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UnsafeURLError(f"{parsed.hostname!r} resolves to a non-public address ({ip}); refusing to fetch")

    return parsed.hostname


def fetch_url_text(url: str) -> FetchedScheme:
    """Tier 4: the user pasted a link to the scheme notification. One GET,
    no redirect following, SSRF-guarded. A PDF response's bytes are read
    with the same PDF text extraction as an uploaded PDF; an HTML response
    is stripped of markup with BeautifulSoup."""
    _assert_safe_url(url)

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise UnsafeURLError(f"fetching {url!r} failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UnsafeURLError(f"fetching {url!r} failed: {exc.reason}") from exc

    if len(body) > _MAX_RESPONSE_BYTES:
        raise UnsafeURLError(f"response from {url!r} exceeds the {_MAX_RESPONSE_BYTES} byte cap")

    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(body)
            tmp_path = Path(tmp.name)
        try:
            return FetchedScheme(text=extract_pdf_text(tmp_path), source="pdf")
        finally:
            tmp_path.unlink(missing_ok=True)

    html = body.decode("utf-8", errors="replace")
    text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
    return FetchedScheme(text=text.strip(), source="url")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects — a redirect could repoint the request at
    an internal address after the SSRF check already passed on the
    original URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802 - stdlib override
        raise UnsafeURLError(f"refusing to follow redirect to {newurl!r}")
