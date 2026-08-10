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
# exactly what produced #285, so this pins the comparison key to LITERALS
# (so a constant function cannot satisfy it) and then pins the two sides to
# each other over the URLs a source row can actually hold.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected_key"),
    [
        ("https://example.com/article#section-2", "https://example.com/article"),
        ("https://example.com/article#", "https://example.com/article"),
        ("https://example.com/article#x#y", "https://example.com/article"),
        ("https://example.com/search?q=foo#frag", "https://example.com/search?q=foo"),
        ("https://example.com/article", "https://example.com/article"),
        (
            "https://example.com/search?q=foo&page=2",
            "https://example.com/search?q=foo&page=2",
        ),
        # Client-side routes fold too, since #285's second round: the store
        # threw the route away, so the row minted from the marker IS the base
        # page (``evaluation._canonical_marker_key``'s docstring measures it).
        ("https://example.com/article#/route", "https://example.com/article"),
        ("https://example.com/article#!/bang", "https://example.com/article"),
        # The non-fragment folds ``_normalize_url`` also performs, pinned so
        # this corpus cannot be satisfied by cutting at ``#`` alone.
        ("https://EXAMPLE.com/Article/#/route", "https://example.com/article"),
        ("https://example.com/article.", "https://example.com/article"),
    ],
)
def test_the_marker_key_folds_a_stored_source_url_to_this_exact_key(
    url: str,
    expected_key: str,
) -> None:
    """The marker key of each URL, written out as a literal.

    This assertion used to read ``_canonical_marker_key(url) ==
    _canonical_marker_key(stored)`` — one function applied to two inputs,
    anchored to no expected value. Measured: replacing the whole body of
    ``_canonical_marker_key`` with ``return ""`` left all six rows GREEN,
    and so did breaking the PRODUCER (``_sanitize_source_url``'s
    ``url.find("#")`` forced to ``-1``), because the comparison side then
    performed the cut on both operands. It could not see either drift its
    section header claims to catch.

    RED if ``_canonical_marker_key`` returns anything but these strings:
    the constant function ``return ""`` fails all ten rows; ``rfind`` for
    ``find`` fails row 3; dropping ``_normalize_url`` fails rows 9 and 10.
    """
    assert _canonical_marker_key(url) == expected_key


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/article#section-2",
        "https://example.com/article#",
        "https://example.com/article#x#y",
        "https://example.com/search?q=foo#frag",
        "https://example.com/article",
        "https://example.com/search?q=foo&page=2",
        "https://example.com/article#/route",
        "https://example.com/article#!/bang",
    ],
)
def test_the_stored_url_keys_the_same_way_the_raw_one_does(url: str) -> None:
    """The PRODUCER half: storing a URL must not change its marker key.

    Kept as a separate test because the table above pins the key and this
    pins the agreement; the one test that tried to be both was neither.

    RED if ``providers._sanitize_source_url`` folds something
    ``_canonical_marker_key`` does not — e.g. cutting at ``?`` as well:
    row 4 then stores ``https://example.com/search`` while the raw marker
    still keys to ``https://example.com/search?q=foo``.

    What it CANNOT see, stated so nobody trusts it for this: the producer
    dropping its fragment cut. Both sides would then cut and still agree.
    That direction is covered by ``test_fragment_stripped`` above and by
    the literal table's rows 1-3.
    """
    stored = _sanitize_source_url(url)
    assert stored is not None
    assert _canonical_marker_key(url) == _canonical_marker_key(stored)
