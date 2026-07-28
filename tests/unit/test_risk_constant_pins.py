"""Module-level constants in risk-tier code must be pinned to a literal value.

**The gap this closes.** The mutation gate cannot see module-level code at all:
mutmut only mutates function bodies, and ~35% of `src/product_app` (5,829 lines)
sits outside every `def`. Measured over real history, **8% of pull requests that
changed `src/` Python produced an EMPTY mutation scope** — and three of the five
real cases were money or model configuration: the daily cap, the web-search fee,
the model id. `docs/metrics/mutation-gate-study.md` §3.1.

Measured before this file existed, with a detector that requires the other side
of the comparison to be a LITERAL: of the 38 module-level constants in risk-tier
modules, **not one carried a literal `== VALUE` assertion**. Every reference was
symbolic (`assert x < DAILY_CAP_USD`, `assert rendered == CONSTANT`), which moves
with the code — change the constant and the test still passes.

The starkest case, and the reason this file is not academic:
`costs._DEFAULT_PRICE_PER_1K_INPUT = 0.0008` — the default behind the recorded
16x mispricing — was referenced only SYMBOLICALLY
(`assert Decimal(cm["default_input_price_per_1k"]) == _DEFAULT_PRICE_PER_1K_INPUT`,
`tests/integration/test_template_data_island_escape.py:89`). That assertion
compares the rendered template against the constant, so it holds no matter what
the constant says. Change 0.0008 to 0.0128 and it stays green.

(An earlier draft of this file claimed the constant had *zero* references and
that its `_OUTPUT` twin was pinned. Adversarial review showed both halves false:
the twin carries the identical symbolic assertion. The error came from a pin
detector that counted `== CONSTANT` as a pin regardless of what the other side
was — the very flaw `test_every_bucket_a_constant_really_has_a_literal_pin` now
exists to prevent. Recorded rather than quietly corrected.)

**Why not pin all 30.** A literal pin on a regex, a filesystem path or a CSP
policy is churn: the value legitimately changes, so the reflex becomes "edit the
test alongside the code", which is the habit this whole exercise exists to
break. Constants are therefore TRIAGED into three buckets below, and
`test_every_risk_constant_is_triaged` fails when a new one belongs to none — so
the decision is forced, never defaulted.
"""

from __future__ import annotations

import ast
import pathlib
import re
from datetime import timedelta
from decimal import Decimal

from product_app import auth, catalog_fetcher, costs, main, model_slots

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "product_app"
TESTS = REPO_ROOT / "tests"

#: The modules whose module-level constants are risk-bearing.
#:
#: KNOWN GAP, stated rather than implied: `config.py` is listed but contributes
#: ZERO constants, because all 41 of its settings are `Settings` class
#: attributes with defaults, not module-level names. So the largest
#: configuration surface in the repo — including
#: `cost_web_search_request_fee_usd`, one of the money changes that produced an
#: empty mutation scope — is NOT covered by this file. Extending the registry to
#: Pydantic field defaults is tracked separately; listing `config.py` here keeps
#: the module in view rather than letting it read as covered by omission.
RISK_TIER_MODULES = (
    "costs.py",
    "config.py",
    "catalog_fetcher.py",
    "model_slots.py",
    "safety.py",
    "auth.py",
    "main.py",
)

#: A wrong value here is silently harmful and nothing else constrains it.
#: Every name must have a literal `== VALUE` assertion in tests/.
BUCKET_A_LITERAL_PIN = (
    "costs.SOFT_THRESHOLD_USD",
    "costs.DAILY_CAP_USD",
    "costs.HARD_LIMIT_USD",
    "costs._DEFAULT_PRICE_PER_1K_INPUT",
    "costs._DEFAULT_PRICE_PER_1K_OUTPUT",
    "costs.CHARS_PER_TOKEN",
    "costs.COST_DISPLAY_QUANTUM",
    "costs.CONFIRMATION_TOKEN_TTL",
    "auth.SESSION_TTL",
    "auth._SESSION_COOKIE_NAME_PREFIXED",
    "auth.CSRF_HEADER_NAME",
    "main._HSTS_HEADER",
    "model_slots.EXPECTED_SLOT_COUNT",
)

#: Pin the BEHAVIOUR, not the literal — these legitimately change, and a literal
#: pin would teach people to edit the test alongside the code.
BUCKET_B_PIN_BEHAVIOUR = {
    "main._CSP_POLICY": "assert the key directives, not the whole string",
    "safety.HIGH_STAKES_PATTERN": (
        "assert it matches 'medical' and not 'weather'; the regex should grow"
    ),
    "safety.WARNING_VERSION": "assert the ISO-date shape, not the value",
    "model_slots._MODEL_ID_RE": "assert accept/reject on samples",
    "catalog_fetcher._VENDOR_RE": "assert accept/reject on samples",
    "main._KNOWN_HTTP_METHODS": "assert non-empty and contains GET/POST",
    "main._PYDANTIC_TYPE_TO_CODE": "assert the mappings the API contract depends on",
    "catalog_fetcher.OPENROUTER_CATALOG_URL": (
        "assert https scheme and openrouter.ai host (SSRF-adjacent)"
    ),
    "auth._SESSION_COOKIE_NAME_UNPREFIXED": (
        "assert where the unprefixed fallback is accepted (F-02)"
    ),
    "auth.LEGACY_CSRF_PLACEHOLDER": "assert the legacy path it marks, not the string",
    "catalog_fetcher.DEFAULT_VENDORS": (
        "assert it equals the vendor set of DEFAULT_MODEL_IDS; it changes on a slot swap"
    ),
    "catalog_fetcher._FALLBACK_CATALOG": (
        "assert every DEFAULT_MODEL_ID has a row; prices change upstream"
    ),
    "model_slots.DEFAULT_MODEL_IDS": (
        "assert the count and that each id resolves in the catalog; ids are swapped"
    ),
    "model_slots.FALLBACK_CATALOG_OPTIONS": (
        "assert the shape the slot picker relies on, not the members"
    ),
    "model_slots.ONLINE_CAPABLE_VENDORS": (
        "assert it stays within DEFAULT_VENDORS; :online support is unverified (study §7)"
    ),
    "model_slots._DEFAULT_MODEL_ID_SET": (
        "derived from DEFAULT_MODEL_IDS; assert they stay consistent"
    ),
    "model_slots._UNAUTHENTICATED_VARIANT_SUFFIXES": (
        "assert the suffixes are stripped, not the literal tuple"
    ),
    "safety.WARNING_COPY": (
        "assert the mandatory caveat is present; the wording is edited deliberately"
    ),
}

#: No pin. A literal here restates the implementation and catches nothing.
BUCKET_C_NO_PIN = {
    "main.TEMPLATES_DIR": "filesystem path, exercised by every template render",
    "main.STATIC_DIR": "filesystem path, exercised by every static fetch",
    "main._FEEDBACK_DIR": "filesystem path, exercised by the feedback store tests",
    "main._APP_START_MONOTONIC": "runtime value, not a configuration choice",
    "main.SENTRY_DSN": "derived from the environment at import",
    "main._VENDOR_PREFIX": "routing prefix, exercised by the routes that use it",
    "costs.DAILY_CAP_BYPASS_LOG_INTERVAL_S": (
        "log throttle; a wrong value costs log volume, not money"
    ),
}


#: Constant-looking names. The floor is 2 trailing chars, not 3: a future
#: `URL`, `TTL`, `CAP` or `FEE` would otherwise be invisible to the whole guard.
_CONST_NAME = re.compile(r"_?[A-Z][A-Z0-9_]{2,}")


def _module_constants() -> dict[str, int]:
    """`module.NAME` -> line, for every module-level constant in a risk module.

    Covers `ast.AnnAssign` as well as `ast.Assign`, and tuple targets. An
    earlier version matched only bare `Assign`, which hid EIGHT constants —
    including `catalog_fetcher.DEFAULT_VENDORS`, `catalog_fetcher._FALLBACK_CATALOG`
    and `model_slots.DEFAULT_MODEL_IDS`, i.e. precisely the surface behind the
    recorded 16x mispricing. Found by adversarial review.
    """
    found: dict[str, int] = {}
    for name in RISK_TIER_MODULES:
        path = SRC / name
        if not path.is_file():
            continue
        module = path.stem
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                targets: list[ast.expr] = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            flat: list[ast.expr] = []
            for target in targets:
                flat.extend(target.elts if isinstance(target, ast.Tuple) else [target])
            for element in flat:
                if isinstance(element, ast.Name) and _CONST_NAME.fullmatch(element.id):
                    found[f"{module}.{element.id}"] = node.lineno
    return found


def _is_literal(node: ast.expr) -> bool:
    """A literal value, or `Decimal("…")`/`timedelta(…)` over literals."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_literal(node.operand)
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in ("Decimal", "timedelta", "frozenset", "Path"):
            return all(_is_literal(a) for a in node.args) and all(
                _is_literal(k.value) for k in node.keywords
            )
    return False


def _literally_pinned_constants() -> set[str]:
    """Constants compared with `==` to a LITERAL inside a real `assert`.

    Parsed with `ast`, per file — NOT a grep over concatenated sources. A grep
    was the first implementation and it accepted, all measured:
      * `assert costs.DAILY_CAP_USD == costs.HARD_LIMIT_USD` (purely symbolic),
      * a commented-out assertion,
      * an assertion inside a string literal in an unrelated file.
    Each satisfied "bucket A is pinned" while pinning nothing.
    """
    pinned: set[str] = set()
    for path in TESTS.rglob("test_*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            for cmp_node in ast.walk(node.test):
                if not isinstance(cmp_node, ast.Compare):
                    continue
                if not all(isinstance(op, ast.Eq) for op in cmp_node.ops):
                    continue
                sides = [cmp_node.left, *cmp_node.comparators]
                for index, side in enumerate(sides):
                    name: str | None
                    if isinstance(side, ast.Attribute):
                        name = side.attr
                    elif isinstance(side, ast.Name):
                        name = side.id
                    else:
                        name = None
                    if not name:
                        continue
                    others = [s for j, s in enumerate(sides) if j != index]
                    if any(_is_literal(other) for other in others):
                        pinned.add(name)
    return pinned


# ---------------------------------------------------------------------------
# The pins themselves. Each is a literal, so changing the constant fails here.
# ---------------------------------------------------------------------------


def test_money_constants_are_pinned_to_their_literal_values() -> None:
    """Turns red if: any spend rail moves. That is the point — it must be reviewed.

    These are statements about real money. `costs._DEFAULT_PRICE_PER_1K_INPUT`
    is the standout: 0.0008 is the default behind the recorded 16x mispricing,
    and it had no test reference at all before this line.
    """
    assert Decimal("0.15") == costs.SOFT_THRESHOLD_USD
    assert Decimal("0.20") == costs.DAILY_CAP_USD
    assert Decimal("0.25") == costs.HARD_LIMIT_USD
    assert Decimal("0.0008") == costs._DEFAULT_PRICE_PER_1K_INPUT
    assert Decimal("0.002") == costs._DEFAULT_PRICE_PER_1K_OUTPUT
    assert Decimal(4) == costs.CHARS_PER_TOKEN
    assert Decimal("0.0001") == costs.COST_DISPLAY_QUANTUM
    assert timedelta(minutes=5) == costs.CONFIRMATION_TOKEN_TTL


def test_the_spend_rails_keep_their_ordering() -> None:
    """The literals above pin the values; this pins the RELATIONSHIP.

    Neither replaces the other: an ordering assertion still passes if all three
    move together, and literal pins still pass if the ordering is inverted by
    swapping two of them.

    Turns red if: soft >= cap, or cap >= hard.
    """
    assert costs.SOFT_THRESHOLD_USD < costs.DAILY_CAP_USD < costs.HARD_LIMIT_USD


def test_auth_and_transport_constants_are_pinned() -> None:
    """Turns red if: the `__Host-` prefix, the CSRF header name, the session
    lifetime, or the HSTS max-age changes.

    The `__Host-` prefix IS the security control (it forces Secure, host-only,
    path=/). A silently shortened HSTS max-age weakens transport security with
    no other visible symptom.
    """
    assert timedelta(hours=2) == auth.SESSION_TTL
    assert auth._SESSION_COOKIE_NAME_PREFIXED == "__Host-quorum_session"
    assert auth.CSRF_HEADER_NAME == "X-CSRF-Token"
    assert main._HSTS_HEADER == "max-age=31536000; includeSubDomains"


def test_the_slot_count_is_pinned() -> None:
    """Turns red if: EXPECTED_SLOT_COUNT moves.

    It drives the "N of 4" honesty banner — the surface that tells a user how
    many models actually answered.
    """
    assert model_slots.EXPECTED_SLOT_COUNT == 4


def test_every_default_model_id_has_a_catalog_row() -> None:
    """The bucket-B pin for the model/pricing surface — and the 16x guard.

    `WP-D-TO-CLOSEOUT` calls this "the one-line guard that would have caught
    WP-G1's half-done swap on day one": the slot-4 model id was changed while
    its `_FALLBACK_CATALOG` row was not, so that model priced at the 0.0008
    default — a 16x mispricing. Nothing asserted it until now.

    A literal pin is wrong here (ids are swapped deliberately); the INVARIANT
    is what must hold.

    Turns red if: a model id is added to DEFAULT_MODEL_IDS with no catalog row.
    """
    catalog_ids = {entry.model_id for entry in catalog_fetcher._FALLBACK_CATALOG}
    assert catalog_ids, "the fallback catalog is empty — this guard would be vacuous"
    missing = sorted(set(model_slots.DEFAULT_MODEL_IDS) - catalog_ids)
    assert not missing, (
        f"default model ids with no _FALLBACK_CATALOG row: {missing}. They price "
        "at the default rate — this is the 16x mispricing shape."
    )


def test_the_default_vendor_set_matches_the_default_model_ids() -> None:
    """The other half of the same swap: the vendor list must follow the ids.

    Turns red if: a slot moves to a new vendor and DEFAULT_VENDORS is not
    updated, or vice versa.
    """
    from_ids = {model_id.split("/")[0] for model_id in model_slots.DEFAULT_MODEL_IDS}
    assert from_ids, "no default model ids — the comparison below would be vacuous"
    assert set(catalog_fetcher.DEFAULT_VENDORS) == from_ids, (
        f"DEFAULT_VENDORS={sorted(catalog_fetcher.DEFAULT_VENDORS)} but the "
        f"default ids use {sorted(from_ids)}"
    )


def test_there_are_exactly_as_many_default_ids_as_slots() -> None:
    """Turns red if: DEFAULT_MODEL_IDS and EXPECTED_SLOT_COUNT drift apart.

    EXPECTED_SLOT_COUNT drives the "N of 4" honesty banner; a mismatch makes
    that banner lie about how many models were asked.
    """
    assert len(model_slots.DEFAULT_MODEL_IDS) == model_slots.EXPECTED_SLOT_COUNT


# ---------------------------------------------------------------------------
# The triage guard: a new constant must be classified, never defaulted.
# ---------------------------------------------------------------------------


def test_the_registry_is_not_empty() -> None:
    """A guard over an empty collection proves nothing.

    Turns red if: the discovery regex or RISK_TIER_MODULES stops matching.
    """
    discovered = _module_constants()
    assert len(discovered) >= 25, f"only {len(discovered)} constants discovered — glob is wrong"
    assert BUCKET_A_LITERAL_PIN and BUCKET_B_PIN_BEHAVIOUR and BUCKET_C_NO_PIN


def test_every_risk_constant_is_triaged() -> None:
    """A new module-level constant in risk code must be put in a bucket.

    This is the load-bearing test. Without it, a new spend rail or auth value
    lands with no pin and nothing notices — which is exactly the state measured
    before this file existed (3 of 30 pinned).

    Turns red if: a constant is added to a risk-tier module and not classified.
    """
    discovered = set(_module_constants())
    triaged = set(BUCKET_A_LITERAL_PIN) | set(BUCKET_B_PIN_BEHAVIOUR) | set(BUCKET_C_NO_PIN)

    untriaged = sorted(discovered - triaged)
    assert not untriaged, (
        f"module-level constants in risk-tier code with no bucket: {untriaged}. "
        "Decide: A (literal pin - a wrong value is silently harmful), "
        "B (pin the behaviour - the value legitimately changes), or "
        "C (no pin - with a one-line reason). Nothing defaults."
    )


def test_the_registry_names_no_constant_that_has_been_deleted() -> None:
    """A registry naming removed symbols rots into a comment.

    Turns red if: a triaged constant is renamed or deleted without updating
    this file.
    """
    discovered = set(_module_constants())
    triaged = set(BUCKET_A_LITERAL_PIN) | set(BUCKET_B_PIN_BEHAVIOUR) | set(BUCKET_C_NO_PIN)
    stale = sorted(triaged - discovered)
    assert not stale, f"triaged constants that no longer exist: {stale}"


def test_every_bucket_a_constant_really_has_a_literal_pin() -> None:
    """Bucket A is a promise; this checks the promise is kept.

    Keys off a literal `== <literal>` comparison in a test, not a mere mention:
    `assert x < DAILY_CAP_USD` is a symbolic reference that moves with the code
    and is exactly what this file exists to replace.

    Turns red if: a constant is added to BUCKET_A_LITERAL_PIN without writing
    its pin (verified by adding a name with no assertion).
    """
    pinned = _literally_pinned_constants()
    missing = sorted(q for q in BUCKET_A_LITERAL_PIN if q.split(".", 1)[1] not in pinned)
    assert not missing, (
        f"bucket A names these but no test compares them to a LITERAL: {missing}. "
        "A symbolic assertion (`assert rendered == CONSTANT`) is not a pin — it "
        "moves with the code."
    )


def test_bucket_c_entries_each_carry_a_reason() -> None:
    """A silent exemption is the same failure in a new coat.

    Turns red if: a constant is exempted with an empty or placeholder reason.
    """
    thin = sorted(k for k, v in BUCKET_C_NO_PIN.items() if len(v.strip()) < 20)
    assert not thin, f"bucket C entries with no real reason: {thin}"
