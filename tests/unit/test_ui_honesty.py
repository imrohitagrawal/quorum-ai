"""UI honesty: assert that user-facing strings don't leak internal details.

Background: the catalog-drift banner was originally a hard-coded string
in ``app.js`` that referenced ``product_app/model_slots.py`` — the
internal source file path. That message was meant for an operator, not
an end user. The fix splits the message: the UI builds a plain, user-
facing string from ``catalog_drift_ids``; the operator-facing detail
is kept in the ``/ready`` JSON response only.

These tests are a guard against the regression: they scan the
user-facing surface (UI HTML, UI JavaScript, the rendered drift banner)
and assert no internal file paths, module names, or operator jargon
leak into what an end user sees.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from product_app.main import app

# Tokens that would only make sense to a developer reading source.
# If any of these appear in a user-facing string, the test fails.
INTERNAL_REFERENCES = [
    "product_app/",  # Python module path
    "model_slots.py",  # Specific source file
    "DEFAULT_MODEL_IDS",  # Source-level constant name
    "DEFAULT_VENDORS",  # Source-level constant name
    "operator should",  # Operator jargon
    "the operator",  # Operator jargon
    "/src/",  # Source-tree path
    "src/product_app",  # Source-tree path
]

# Strings used by the user-facing drift banner UI region.
# We extract any string the UI sets on the drift-message element and
# assert it's free of internal references.
USER_FACING_SURFACES = [
    "src/product_app/static/app.js",
    "src/product_app/templates/workspace.html",
]


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _extract_user_facing_drift_message(app_js: str) -> str:
    """Pull the user-facing string the drift banner builds.

    The banner assigns to ``driftMessage.textContent``. Earlier
    versions used a single template literal; the current version
    builds a message from local variables (names, action) with
    template-literal interpolation. We extract the full assignment
    expression — that's the user-visible string after JS evaluates
    the concatenation. The result is a string containing the literal
    parts and ``${...}`` placeholders; we assert against the literal
    parts because the dynamic parts are runtime data, not source code.
    """
    match = re.search(
        r"driftMessage\.textContent\s*=\s*([\s\S]*?);",
        app_js,
    )
    if not match:
        return ""
    raw = match.group(1)
    # Extract all backtick-delimited template-literal fragments —
    # these are the static parts of the message. Skip ${...}
    # interpolations because they reference runtime data.
    fragments = re.findall(r"`([^`]*)`", raw)
    # Also extract double-quoted string literals (the ``action`` variable
    # is built from a ternary of two string literals).
    fragments.extend(re.findall(r'"([^"]*)"', raw))
    fragments.extend(re.findall(r"'([^']*)'", raw))
    return "\n".join(fragments)


def test_drift_banner_user_facing_string_omits_internal_references() -> None:
    """The user-facing drift banner must not mention source files or operators."""
    app_js = _read(USER_FACING_SURFACES[0])
    fragments = _extract_user_facing_drift_message(app_js)
    assert fragments, "Could not locate driftMessage.textContent in app.js"
    for ref in INTERNAL_REFERENCES:
        assert ref not in fragments, (
            f"User-facing drift banner contains internal reference: {ref!r}\n"
            f"Fragments: {fragments!r}\n"
            f"Internal references must be kept in the operator-facing "
            f"/ready JSON response, not in the UI."
        )


def test_workspace_html_omits_internal_references() -> None:
    """The HTML template must not contain source-path leaks in the
    user-visible text. ``window.DEFAULT_MODEL_IDS`` and similar
    assignments are JS data islands, not user-visible strings, so
    this test only scans the rendered text content of the page.
    """
    html = _read(USER_FACING_SURFACES[1])
    # Strip JS data islands (script-embedded JSON or JS variables)
    # before scanning. These are not user-visible text.
    visible = re.sub(r"<script[\s\S]*?</script>", " ", html)
    visible = re.sub(r"<style[\s\S]*?</style>", " ", visible)
    for ref in INTERNAL_REFERENCES:
        assert ref not in visible, (
            f"workspace.html visible text contains internal reference: {ref!r}"
        )


def test_rendered_ui_with_drift_does_not_leak_paths() -> None:
    """End-to-end: render the UI, scan the served HTML for user-visible leaks.

    Script tags are stripped before scanning because they contain JS
    data islands (``window.DEFAULT_MODEL_IDS``, JSON blobs) that are
    not user-visible text. The user only sees what is in <body> tags
    outside <script> blocks.
    """
    client = TestClient(app)
    response = client.get("/ui")
    assert response.status_code == 200
    body = response.text
    visible = re.sub(r"<script[\s\S]*?</script>", " ", body)
    visible = re.sub(r"<style[\s\S]*?</style>", " ", visible)
    for ref in INTERNAL_REFERENCES:
        assert ref not in visible, f"Rendered /ui visible text contains internal reference: {ref!r}"


# CSS rule that forces the cancel-run container to honor the HTML
# ``hidden`` attribute. Without this, the container's ``display: flex``
# rule wins and the cancel button is visible (and clickable) when no
# run is in flight. The user flagged this as a bug. The fix: a
# ``!important`` rule keyed off ``[hidden]``.
_CSS_HIDDEN_OVERRIDE = ".run-controls-cancel[hidden]" in _read("src/product_app/static/app.css")


def test_cancel_button_hidden_when_no_run_in_progress() -> None:
    """The cancel-run container must hide when the ``hidden`` attribute is set.

    Regression guard for: CSS ``display: flex`` was overriding the
    HTML ``hidden`` attribute, so the cancel button was always visible
    and clickable — even when no run was in flight. Clicking it was
    a no-op (the JS handler checks ``state.isRunning``) but the user
    saw an active, clickable button.
    """
    assert _CSS_HIDDEN_OVERRIDE, (
        "CSS must include a .run-controls-cancel[hidden] { display: none } "
        "rule so the cancel container actually hides when the HTML "
        "hidden attribute is set."
    )


# --- ADR-0032: the served API description must not claim peer critique -------
#
# `main.py`'s OpenAPI `info.description` said "has them debate", served at
# /openapi.json and /docs to every API consumer. It is a module-level string
# constant, so NO coverage or mutation gate can see it change — diff-cover's
# own floor said exactly that when this line was edited ("the 95% you are about
# to see is over an empty denominator"). This is the pinned literal assertion
# that blind spot calls for.
#
# The four answer models are called once each and never read each other; one
# separate moderator call (`settings.debate_model_id`) reads all four. See
# ADR-0032 and issue #290.


def test_api_description_does_not_claim_the_models_debate_each_other() -> None:
    """RED IF: the OpenAPI description returns to claiming mutual critique.

    Mutation that reddens this: restore "has them debate," in the
    ``description=`` block of ``build_app`` in ``src/product_app/main.py``.
    """
    description = app.openapi()["info"]["description"].lower()

    # POSITIVE PARTNER FIRST (rule 7). Without these, every negative below is
    # trivially true over an empty or missing description.
    assert len(description) > 200, (
        "description is missing or truncated; the negatives below would pass vacuously"
    )
    assert "moderator model" in description
    assert "synthesis model" in description

    for banned in (
        "has them debate",
        "critique each other",
        "critique one another",
        "debate each other",
    ):
        assert banned not in description, (
            f"the served API description claims {banned!r}; the four answer "
            "models are called once each and never read each other (ADR-0032)"
        )


# --- the debate section's copy (ADR-0063) -----------------------------------
#
# `#result-debate` puts the round critiques on the page a completed run lands
# on. That is the first time this copy is visible to anyone: the same content
# was previously rendered only into `.panel.panel-section`, which app.css hides
# with `display: none` on every view.
#
# The honesty rule it must not break: the four answer models are called ONCE
# EACH, IN PARALLEL, and never read one another. Real peer critique is #290 and
# is NOT built. The backend records ONE `critique_text` per round with NO
# per-model attribution.
#
# WHY THIS SCANS STRING LITERALS AND NOT THE FILE. `app.js`'s comments around
# this code deliberately spell out the banned phrases in order to explain the
# rule ("they never read each other", "implies they argued WITH EACH OTHER").
# A substring scan over the file would match the prose that EXPLAINS the thing
# rather than the thing — the exact trap `tests/code_text.py` was written for,
# and `code_without_comments` cannot help here because it strips `#` comments,
# not JavaScript `//` ones. So this locates the specific `mkEl(...)` copy sites
# and reads their literal arguments.

#: Phrases that assert the four models exchanged views with each other.
#: Lowercased; matched against the debate section's user-facing copy only.
BANNED_EXCHANGE_CLAIMS = (
    "each other",
    "one another",
    "read the other",
    "rebuttal",
    "replied",
    "reply to",
    "responded to",
    "in turn",
    "back and forth",
    "argued with",
    "peer critique",
)

#: Copy sites in the debate section, by the class name passed to ``mkEl``.
DEBATE_COPY_CLASSES = (
    "result-debate-title",
    "result-debate-caption",
    "transcript-round-templated",
)


def _extract_mkel_literals(app_js: str, class_name: str) -> str:
    """Return the concatenated string literals ``mkEl`` is given for *class_name*.

    Matches ``mkEl("span", "<class_name>", <args...>)`` and pulls every
    double-quoted literal from the argument list, so a caption built by
    concatenating two literals across lines is read as one string.
    """
    match = re.search(
        r'mkEl\(\s*"[a-z]+"\s*,\s*"' + re.escape(class_name) + r'"\s*,([\s\S]*?)\)\s*,?\s*\n',
        app_js,
    )
    if not match:
        return ""
    return " ".join(re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1)))


def test_the_debate_section_copy_does_not_claim_the_models_answered_each_other() -> None:
    """RED IF: the result view's debate copy starts describing #290.

    Mutation that reddens this: change the ``result-debate-caption`` literal in
    ``renderResultDebate`` to "Each model read the other three answers and
    replied in turn." — measured, and it fails on "read the other".

    This is the unit-level partner to
    ``e2e/tests/invariants/result-debate.spec.ts``'s
    "neither the heading nor the caption claims the models answered each other",
    which asserts the same rule against the RENDERED DOM. Both exist because the
    e2e one cannot run in the pytest lane and this one cannot see what actually
    reaches the screen.
    """
    app_js = _read(USER_FACING_SURFACES[0])

    found: dict[str, str] = {}
    for class_name in DEBATE_COPY_CLASSES:
        found[class_name] = _extract_mkel_literals(app_js, class_name)

    # POSITIVE PARTNER FIRST (rule 7). Every negative below is trivially true
    # over copy the regex failed to locate — which is how this test would rot
    # silently if the call shape changed.
    for class_name, copy in found.items():
        assert copy, (
            f"could not locate the {class_name!r} copy in app.js; the negatives "
            "below would pass vacuously. Fix the extractor, do not delete this."
        )
    assert "per round" in found["result-debate-caption"].lower(), (
        "the caption no longer states the ROUND-LEVEL shape, which is the one "
        "thing it exists to say"
    )

    for class_name, copy in found.items():
        lowered = copy.lower()
        for banned in BANNED_EXCHANGE_CLAIMS:
            assert banned not in lowered, (
                f"{class_name} says {banned!r} — the four answer models are "
                "called once each and never read each other (#290 is not built, "
                "ADR-0032, ADR-0063). Copy was: {copy!r}".format(copy=copy)
            )


def test_the_debate_caption_makes_no_unconditional_authorship_claim() -> None:
    """RED IF: the debate caption attributes the critique to a model outright.

    ``debate_mode`` is ``"live"`` only when the configured moderator's own
    response supplied the text; on ``"fallback"`` ``critique_text`` is Quorum's
    own template (``debate.py::_build_round_one_text``). A caption reading
    "written by the moderator" is therefore false on every fallback round, and
    the API schema's default for that field is ``"fallback"``.

    Authorship may only be stated per-round, conditioned on ``debate_mode`` —
    which ``buildTranscriptRound`` does. So the section-level caption must make
    no authorship claim at all.

    Mutation that reddens this: restore "written by the moderator across all
    four answers" to the ``result-debate-caption`` literal.
    """
    app_js = _read(USER_FACING_SURFACES[0])
    caption = _extract_mkel_literals(app_js, "result-debate-caption")
    assert caption, "could not locate the debate caption; the negatives would be vacuous"

    for banned in ("written by the moderator", "written by a model", "the moderator wrote"):
        assert banned not in caption.lower(), (
            f"the debate caption claims {banned!r} unconditionally, but "
            "debate_mode can be 'fallback', in which case Quorum's own template "
            "wrote the critique (ADR-0063)"
        )

    # POSITIVE PARTNER: the per-round marker that IS allowed to speak about
    # authorship must still exist, or this test would be satisfied by a UI that
    # simply never discloses provenance at all.
    assert 'round.debate_mode !== "live"' in app_js, (
        "the per-round provenance guard is gone; dropping the caption's "
        "authorship claim is only honest if the per-round marker replaces it"
    )
    marker = _extract_mkel_literals(app_js, "transcript-round-templated")
    assert "quorum" in marker.lower() and "not by a model" in marker.lower(), (
        f"the fallback marker no longer says Quorum wrote it; got {marker!r}"
    )
