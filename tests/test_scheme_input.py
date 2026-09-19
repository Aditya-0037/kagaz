"""Scheme input tiers: pure functions and the SSRF guard, no network."""

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
