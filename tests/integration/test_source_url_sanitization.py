"""Source URLs must be sanitized against loopback/metadata hosts
and have fragments stripped before they are emitted in a citation.

The citation comes from the upstream LLM provider (via the
``annotations`` or ``citations`` array on the chat-completions
response). A crafted prompt could instruct the model to include a
URL pointing at a metadata service (e.g. ``169.254.169.254``) or
the loopback interface. The sanitizer must drop those URLs before
they reach the response.

Fragments (``#...``) must be stripped because they collide with
the SPA's own hash routing and can be used to smuggle javascript:
into a previously-validated URL when the URL is opened in a new
tab by a downstream consumer.
"""

from __future__ import annotations

from product_app.providers import _sanitize_source_url


def test_https_passthrough() -> None:
    assert _sanitize_source_url("https://example.com/path") == "https://example.com/path"


def test_http_passthrough() -> None:
    assert _sanitize_source_url("http://example.com/path") == "http://example.com/path"


def test_fragment_stripped() -> None:
    assert (
        _sanitize_source_url("https://example.com/article#section-2")
        == "https://example.com/article"
    )


def test_fragment_only_stripped() -> None:
    assert (
        _sanitize_source_url("https://example.com/article#")
        == "https://example.com/article"
    )


def test_localhost_denied() -> None:
    assert _sanitize_source_url("http://localhost/admin") is None


def test_loopback_ip_denied() -> None:
    assert _sanitize_source_url("http://127.0.0.1:8080/admin") is None
    assert _sanitize_source_url("http://0.0.0.0/admin") is None


def test_aws_metadata_denied() -> None:
    assert (
        _sanitize_source_url("http://169.254.169.254/latest/meta-data")
        is None
    )


def test_gcp_metadata_denied() -> None:
    assert (
        _sanitize_source_url("http://metadata.google.internal/computeMetadata/v1/")
        is None
    )


def test_ipv6_loopback_denied() -> None:
    assert _sanitize_source_url("http://[::1]/admin") is None


def test_non_http_scheme_rejected() -> None:
    assert _sanitize_source_url("javascript:alert(1)") is None
    assert _sanitize_source_url("file:///etc/passwd") is None
    assert _sanitize_source_url("data:text/html,<script>alert(1)</script>") is None


def test_empty_string_rejected() -> None:
    assert _sanitize_source_url("") is None


def test_query_string_preserved() -> None:
    """Query strings are legitimate URL features and must not be
    stripped — they often carry search parameters the user wants
    to drill into.
    """
    assert (
        _sanitize_source_url("https://example.com/search?q=foo&page=2")
        == "https://example.com/search?q=foo&page=2"
    )
