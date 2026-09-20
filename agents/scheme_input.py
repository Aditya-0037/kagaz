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
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from agents.requirement_extractor import extract_pdf_text
from tools.ocr import extract_text as ocr_extract_text

_REQUEST_TIMEOUT_SECONDS = 15
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB — a scheme notice is text/PDF, never larger
_USER_AGENT = "Kagaz/1.0 (+single-page fetch for a user-pasted scheme URL; no crawling)"


# Below this many characters of real text, a fetched page is treated as
# having no content worth extracting from (a JS-rendered shell) rather
# than as a scheme notification.
MIN_USABLE_TEXT = 400


class UnsafeURLError(ValueError):
    """Raised by fetch_url_text when a URL fails the SSRF guard."""


class ThinPageError(ValueError):
    """Raised when a fetch succeeded but the page carried no usable text —
    almost always a JavaScript-rendered portal."""


def _clean_html_text(text: str) -> str:
    """Collapse the runs of blank lines HTML-to-text extraction leaves
    behind. Cosmetic for a human, but it also stops nav/whitespace noise
    from dominating the model's view of the page."""
    lines = [line.strip() for line in text.splitlines()]
    kept = [line for line in lines if line]
    return "\n".join(kept).strip()


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


def from_screenshots(image_paths: Sequence[Path | str], *, cache_dir: Path, llm_mode: str = "live") -> str:
    """Several screenshots of one notification, in the order given.

    A notification almost never fits on one screen — eligibility is at the
    top, the document list in the middle, the deadline at the bottom — so
    reading only the first image would routinely miss half the
    requirements. Each is read separately and concatenated, because the
    extractor works on one block of text.
    """
    parts: list[str] = []
    for index, path in enumerate(image_paths, start=1):
        text = ocr_extract_text(path, cache_dir=cache_dir, llm_mode=llm_mode).strip()
        if text:
            parts.append(f"--- page {index} of {len(image_paths)} ---\n{text}")
    return "\n\n".join(parts)


def from_pdf_uploads(pdf_paths: Sequence[Path | str]) -> str:
    """Several PDFs making up one notification (an annexure filed
    separately from the main notice, most often)."""
    parts: list[str] = []
    for index, path in enumerate(pdf_paths, start=1):
        text = extract_pdf_text(path).strip()
        if text:
            parts.append(f"--- document {index} of {len(pdf_paths)} ---\n{text}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# One box that takes anything
# --------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic"}
_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".rtf"}


@dataclass
class CollectedInput:
    text: str
    sources: list[str]  # human-readable, for showing the user what was read
    source_kind: str  # the Requirement.source value to record
    problems: list[str]  # non-fatal: a link that failed while files worked


def _read_one_file(path: Path, *, cache_dir: Path, llm_mode: str) -> tuple[str, str]:
    """(text, kind) from a single file, routed by what it actually is
    rather than by which upload box the user happened to pick."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path), "pdf"
    if suffix in _TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace"), "text"
    if suffix in _IMAGE_SUFFIXES:
        return ocr_extract_text(path, cache_dir=cache_dir, llm_mode=llm_mode), "screenshot"
    # Unknown extension: try reading it as an image, since a phone photo
    # saved without an extension is far more likely than a binary blob.
    return ocr_extract_text(path, cache_dir=cache_dir, llm_mode=llm_mode), "screenshot"


def collect_scheme_input(
    file_paths: Sequence[Path] | None = None,
    pasted: str = "",
    *,
    cache_dir: Path,
    llm_mode: str = "live",
) -> CollectedInput:
    """Take everything the user gave us — any mix of images, PDFs, text
    files, pasted text and pasted links — and return one block of text.

    The point is that the user should never have to classify their own
    input. Asking someone to convert a screenshot to PDF, or to know
    which tab their material belongs in, adds exactly the kind of
    busywork this tool exists to remove: if they have to reformat
    something to use Kagaz, they may as well have filled the form by hand.

    A link that fails does not fail the whole submission — it is reported
    alongside whatever else was read successfully.
    """
    parts: list[str] = []
    sources: list[str] = []
    problems: list[str] = []
    kinds: list[str] = []

    for path in file_paths or []:
        try:
            text, kind = _read_one_file(Path(path), cache_dir=cache_dir, llm_mode=llm_mode)
        except Exception as exc:  # noqa: BLE001 - one unreadable file shouldn't sink the rest
            problems.append(f"Couldn't read {Path(path).name}: {exc}")
            continue
        text = text.strip()
        if text:
            parts.append(f"--- from {Path(path).name} ---\n{text}")
            sources.append(Path(path).name)
            kinds.append(kind)
        else:
            problems.append(f"{Path(path).name} had no readable text in it.")

    pasted = (pasted or "").strip()
    if pasted:
        urls = _URL_RE.findall(pasted)
        for url in urls:
            try:
                fetched = fetch_url_text(url)
            except (UnsafeURLError, ThinPageError) as exc:
                problems.append(f"{url} — {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{url} — could not be read: {exc}")
                continue
            parts.append(f"--- from {url} ---\n{fetched.text}")
            sources.append(url)
            kinds.append("url")

        # Whatever the user typed besides the links is content too.
        remainder = _URL_RE.sub(" ", pasted).strip()
        if len(remainder) > 40:
            parts.append(f"--- pasted text ---\n{remainder}")
            sources.append("pasted text")
            kinds.append("text")

    # One source kind is recorded on the Requirement; with a mix, name the
    # dominant one rather than inventing a new contract value.
    source_kind = "text"
    for candidate in ("pdf", "screenshot", "url", "text"):
        if candidate in kinds:
            source_kind = candidate
            break

    return CollectedInput(
        text="\n\n".join(parts).strip(), sources=sources, source_kind=source_kind, problems=problems
    )


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
    text = _clean_html_text(BeautifulSoup(html, "html.parser").get_text(separator="\n"))

    if len(text) < MIN_USABLE_TEXT:
        # Most scheme portals are JavaScript-rendered: the HTML served to a
        # plain GET is an empty shell, so this "succeeds" with a page title
        # and nothing else. Extracting a checklist from that produces
        # confident nonsense — say what happened and what to do instead.
        raise ThinPageError(
            "That page returned almost no readable text — it builds its content with "
            "JavaScript, which a direct fetch can't run. Take a screenshot of the "
            "notification and upload that instead, or copy the text and paste it."
        )

    return FetchedScheme(text=text, source="url")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects — a redirect could repoint the request at
    an internal address after the SSRF check already passed on the
    original URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802 - stdlib override
        raise UnsafeURLError(f"refusing to follow redirect to {newurl!r}")
