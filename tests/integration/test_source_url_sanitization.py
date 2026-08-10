"""Source URLs must be sanitized against loopback/metadata hosts
and have fragments stripped before they are emitted in a citation.

The citation comes from the upstream LLM provider (via the
``annotations`` or ``citations`` array on the chat-completions
response). A crafted prompt could instruct the model to include a
URL pointing at a metadata service (e.g. ``169.254.169.254``) or
the loopback interface. The sanitizer must drop those URLs before
they reach the response.

Fragments (``#...``) are stripped. The reason this file gave until #285 —
that they collide with the SPA's own hash routing and can smuggle
``javascript:`` into a previously-validated URL — was wrong on both
counts: this app has no hash router and no iframe, and the scheme gate
runs BEFORE the fragment cut. The reasons that do hold are recorded on
``providers._sanitize_source_url``. What matters for these tests is that
the stripped shape is a CONTRACT, and that the evaluation engine compares
citation markers in that same shape (``evaluation._canonical_marker_key``)
— which it did not until #285.
"""

from __future__ import annotations

import pytest

from product_app.evaluation import _canonical_marker_key
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
    assert _sanitize_source_url("https://example.com/article#") == "https://example.com/article"


def test_localhost_denied() -> None:
    assert _sanitize_source_url("http://localhost/admin") is None


def test_loopback_ip_denied() -> None:
    assert _sanitize_source_url("http://127.0.0.1:8080/admin") is None
    assert _sanitize_source_url("http://0.0.0.0/admin") is None


def test_aws_metadata_denied() -> None:
    assert _sanitize_source_url("http://169.254.169.254/latest/meta-data") is None


def test_gcp_metadata_denied() -> None:
    assert _sanitize_source_url("http://metadata.google.internal/computeMetadata/v1/") is None


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


# --------------------------------------------------------------------------
# Issue #285 — the producer and the comparison must not drift apart.
#
# ``_sanitize_source_url`` decides the shape a source row is STORED in;
# ``evaluation._canonical_marker_key`` decides the shape a citation marker
# is COMPARED in. Two independent implementations of "cut the fragment" is
# exactly what produced #285, so this pins them to the same answer over the
# URLs a source row can actually hold.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/article#section-2",
        "https://example.com/article#",
        "https://example.com/article#x#y",
        "https://example.com/search?q=foo#frag",
        "https://example.com/article",
        "https://example.com/search?q=foo&page=2",
    ],
)
def test_the_marker_key_agrees_with_the_sanitiser_on_a_stored_source_url(url: str) -> None:
    """Keying the raw URL and keying the STORED URL must give one answer.

    Deliberately excludes client-side ROUTE fragments (``#/``, ``#!``):
    the marker key leaves those alone on purpose — see
    ``test_a_client_side_hash_route_is_not_folded_into_the_page_it_routes_from``
    — so the two sides differ there BY DESIGN, and this corpus would be
    asserting the opposite of the intended behaviour if it included them.

    RED if ``_canonical_marker_key`` cuts at the LAST ``#`` instead of the
    first (``rfind`` for ``find``): row 3 then keys to
    ``https://example.com/article#x`` on the marker side and
    ``https://example.com/article`` on the stored side.
    """
    stored = _sanitize_source_url(url)
    assert stored is not None
    assert _canonical_marker_key(url) == _canonical_marker_key(stored)
