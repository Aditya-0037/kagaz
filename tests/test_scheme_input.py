"""Scheme input tiers: pure functions and the SSRF guard, no network."""

from pathlib import Path

import pytest

from agents.scheme_input import UnsafeURLError, _assert_safe_url, from_pasted_text


def test_pasted_text_is_stripped_not_transformed():
    assert from_pasted_text("  Scheme rules here.  \n") == "Scheme rules here."


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/scheme.pdf",
        "file:///etc/passwd",
        "http://127.0.0.1/admin",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://10.0.0.5/internal",
        "http://192.168.1.1/router",
        "http://[::1]/admin",
        "http:///no-host",
    ],
)
def test_unsafe_urls_are_rejected(url):
    with pytest.raises(UnsafeURLError):
        _assert_safe_url(url)


def test_public_https_url_passes_the_guard():
    assert _assert_safe_url("https://example.com/scheme-notice.pdf") == "example.com"


def test_unresolvable_host_is_rejected():
    with pytest.raises(UnsafeURLError):
        _assert_safe_url("http://this-host-does-not-exist.invalid/scheme.pdf")


def test_multiple_screenshots_are_read_in_order_and_joined(tmp_path, monkeypatch):
    # A notification rarely fits on one screen: eligibility at the top,
    # the document list in the middle, the deadline at the bottom.
    # Reading only the first image would routinely miss half the rules.
    import agents.scheme_input as scheme_input

    texts = {"a.jpg": "ELIGIBILITY", "b.jpg": "DOCUMENTS REQUIRED", "c.jpg": "LAST DATE 2026-12-31"}
    monkeypatch.setattr(scheme_input, "ocr_extract_text", lambda p, **kw: texts[Path(p).name])

    paths = [tmp_path / name for name in ["a.jpg", "b.jpg", "c.jpg"]]
    out = scheme_input.from_screenshots(paths, cache_dir=tmp_path)

    assert out.index("ELIGIBILITY") < out.index("DOCUMENTS REQUIRED") < out.index("LAST DATE")
    assert "page 1 of 3" in out and "page 3 of 3" in out


def test_blank_screenshots_are_skipped_not_padded(tmp_path, monkeypatch):
    import agents.scheme_input as scheme_input

    monkeypatch.setattr(
        scheme_input, "ocr_extract_text", lambda p, **kw: "" if Path(p).name == "blank.jpg" else "REAL TEXT"
    )
    out = scheme_input.from_screenshots([tmp_path / "blank.jpg", tmp_path / "ok.jpg"], cache_dir=tmp_path)
    assert out.count("REAL TEXT") == 1
    assert "page 1 of 2" not in out  # the blank one contributed nothing


def test_a_javascript_rendered_page_is_reported_not_silently_extracted(monkeypatch):
    # buddy4study.com returned 62 characters — just the page title —
    # because the content is rendered client-side. Feeding that to the
    # extractor produces a confident checklist from nothing.
    import agents.scheme_input as scheme_input

    class FakeResponse:
        headers = {"Content-Type": "text/html"}

        def read(self, _n):
            return b"<html><head><title>Scholarships 2026</title></head><body><div id='root'></div></body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(scheme_input, "_assert_safe_url", lambda url: "example.com")
    monkeypatch.setattr(
        scheme_input.urllib.request, "build_opener", lambda *a, **k: type("O", (), {"open": lambda s, r, timeout: FakeResponse()})()
    )

    with pytest.raises(scheme_input.ThinPageError) as exc:
        scheme_input.fetch_url_text("https://example.com/scheme")
    assert "screenshot" in str(exc.value).lower()


def test_html_text_extraction_collapses_blank_line_runs():
    from agents.scheme_input import _clean_html_text

    assert _clean_html_text("A\n\n\n\n\nB\n   \n  C  ") == "A\nB\nC"


def test_one_box_reads_a_mix_of_images_pdfs_and_pasted_text(tmp_path, monkeypatch):
    # The whole point: a user should never have to classify or convert
    # their own material. A screenshot, a PDF and some pasted text in one
    # submission must all be read together.
    import agents.scheme_input as scheme_input

    monkeypatch.setattr(scheme_input, "ocr_extract_text", lambda p, **kw: "FROM THE SCREENSHOT")
    monkeypatch.setattr(scheme_input, "extract_pdf_text", lambda p: "FROM THE PDF")

    shot = tmp_path / "screen.png"; shot.write_bytes(b"x")
    pdf = tmp_path / "notice.pdf"; pdf.write_bytes(b"x")

    out = scheme_input.collect_scheme_input(
        [shot, pdf],
        "Some rules I copied off the portal, long enough to count as real content.",
        cache_dir=tmp_path,
    )

    assert "FROM THE SCREENSHOT" in out.text
    assert "FROM THE PDF" in out.text
    assert "Some rules I copied" in out.text
    assert out.sources == ["screen.png", "notice.pdf", "pasted text"]
    assert out.problems == []


def test_a_link_inside_pasted_text_is_fetched(tmp_path, monkeypatch):
    import agents.scheme_input as scheme_input

    monkeypatch.setattr(
        scheme_input,
        "fetch_url_text",
        lambda url: scheme_input.FetchedScheme(text="PAGE CONTENT", source="url"),
    )
    out = scheme_input.collect_scheme_input(
        [], "have a look at https://example.com/scheme-notice", cache_dir=tmp_path
    )
    assert "PAGE CONTENT" in out.text
    assert out.sources == ["https://example.com/scheme-notice"]


def test_a_failing_link_does_not_lose_the_files_that_worked(tmp_path, monkeypatch):
    import agents.scheme_input as scheme_input

    monkeypatch.setattr(scheme_input, "ocr_extract_text", lambda p, **kw: "GOOD SCREENSHOT TEXT")

    def boom(url):
        raise scheme_input.ThinPageError("that page is JavaScript-rendered")

    monkeypatch.setattr(scheme_input, "fetch_url_text", boom)

    shot = tmp_path / "s.png"; shot.write_bytes(b"x")
    out = scheme_input.collect_scheme_input([shot], "https://example.com/js-page", cache_dir=tmp_path)

    assert "GOOD SCREENSHOT TEXT" in out.text  # the screenshot still counted
    assert len(out.problems) == 1
    assert "JavaScript" in out.problems[0]


def test_an_unreadable_file_is_reported_without_sinking_the_others(tmp_path, monkeypatch):
    import agents.scheme_input as scheme_input

    def ocr(path, **kw):
        if Path(path).name == "broken.png":
            raise ValueError("cannot identify image file")
        return "FINE"

    monkeypatch.setattr(scheme_input, "ocr_extract_text", ocr)

    good = tmp_path / "good.png"; good.write_bytes(b"x")
    bad = tmp_path / "broken.png"; bad.write_bytes(b"x")
    out = scheme_input.collect_scheme_input([bad, good], "", cache_dir=tmp_path)

    assert "FINE" in out.text
    assert any("broken.png" in p for p in out.problems)
