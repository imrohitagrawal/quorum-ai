"""Safety warning policy and acknowledgement tracking.

The policy classifies user queries into a small set of warning types:

* ``SENSITIVE_DATA`` — always required. Reminds the user not to paste
  secrets, PII, or regulated personal data into the prompt.
* ``HIGH_STAKES`` — required when the query mentions topics that would
  turn the synthesis into medical, legal, financial, safety, or regulated
  professional advice if the user acts on it without review.

Both warning types carry a ``version`` so the server can detect when the
client is acknowledging an out-of-date copy of the warning. The
``model_dump()``-style serialisation never includes the raw query text.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from product_app.feedback_store import record_event as _record_feedback_event
from product_app.synthesis_length import _CaveatEnforcer

WARNING_VERSION = "2026-06-17"

# Word-boundary matcher for high-stakes keywords. See
# `tests/unit/test_high_stakes_keyword_uses_word_boundaries.py` for the
# negative cases it has to pass.
HIGH_STAKES_PATTERN = re.compile(
    r"\b("
    r"diagnosis|medical|medicine|doctor|"
    r"lawyer|legal|lawsuit|contract|"
    r"tax(?!\w)|investment|financial|loan|insurance|"
    r"safety|hazard|regulated|compliance"
    r")\b",
    re.IGNORECASE,
)


#: Issue #155. Matches THIS APP'S OWN mandated decision-support caveat, so it
#: can be removed from ``context`` before the high-stakes scan runs.
#:
#: Why any of this is needed: both ``context`` values reach a provider prompt
#: (``prior_question`` the system message, ``prior_synthesis`` the synthesis
#: user message since WP-G2), so high-stakes wording placed there used to skip
#: the acknowledgement entirely. But the obvious fix — scan the context too —
#: was shipped and REVERTED in review, because ``synthesis_length`` guarantees
#: that caveat is present in 100% of recommendations and it matches
#: ``HIGH_STAKES_PATTERN`` five times ("medical", "legal", "financial",
#: "safety", "regulated"). Scanning it wholesale made every legitimate
#: follow-up — a client re-sending this app's own output — demand a
#: high-stakes ack. Measured in
#: ``tests/unit/test_high_stakes_context_discriminator.py``.
#:
#: THE STRIP MAY ONLY EVER CONSUME THE CAVEAT'S OWN WORDS. That constraint is
#: the security property, and getting it wrong is not hypothetical — the first
#: version of this used wildcards
#: (``r"[^.!?]*\bdecision support only\b[^.!?]*\badvice\s*\."``) and adversarial
#: review broke it 4 attempts out of 4. ``[^.!?]*`` is greedy and unanchored, so
#: it ran BACKWARDS over any hostile text sharing the sentence:
#:
#:     "I need a medical diagnosis for my lawsuit but this is decision
#:      support only and is not professional advice."   -> stripped to " "
#:
#: Every high-stakes word vanished before the scan — a cleaner bypass than the
#: one this issue exists to fix. Any "delete a span between two landmarks"
#: shape has that flaw, because the attacker chooses what sits in the span.
#:
#: So the pattern is BUILT FROM the caveat's own tokens, joined by a separator
#: class that matches only whitespace and commas. There is no wildcard for an
#: attacker to hide words in: an injected word between two caveat tokens simply
#: fails the match, the text is left intact, and the scanner sees it.
#:
#: The cost is that a caveat the model REWORDS (rather than merely
#: re-punctuates) no longer matches, so such a follow-up asks for a high-stakes
#: ack it does not strictly need. That direction is deliberate: an unnecessary
#: acknowledgement is a small friction the client can satisfy, while a missed
#: one is the safety control not running.
#:
#: THE OPENING CLAUSE IS OPTIONAL because THIS APP TRUNCATES ITS OWN CAVEAT.
#: ``synthesis_length._truncate_with_caveat_present`` locates the caveat by the
#: marker ``"decision support only"`` and returns ``text[caveat_idx:]``, which
#: DROPS the leading ``"This summary is "``. So a Recommendation over
#: ``RECOMMENDATION_MAX_CHARS`` ships a caveat starting mid-sentence. Measured
#: (adversarial review, second round): a ~1500-char body is unaffected, a
#: ~2100-char body is mangled and the follow-up got a spurious 422 — the exact
#: regression that got the first attempt at this issue reverted, narrowed but
#: not gone. An earlier draft of this comment claimed the verbatim sentence was
#: "the guaranteed floor ... so the common path is covered exactly". That was
#: FALSE on the truncation path; corrected here rather than quietly dropped.
#:
#: Making the opening optional costs nothing in safety: the remaining tokens are
#: still literals with no wildcard between them, so a match still consumes only
#: the caveat's own words.
#: IMPORTED, not duplicated. An earlier draft copied the sentence here and
#: justified it with "``safety`` sits below ``synthesis`` and must not import
#: upward" — which review showed to be FALSE for the module that actually
#: owns the string: ``synthesis_length`` imports nothing from
#: ``product_app`` (only ``re``), so there is no cycle and no reason for a
#: third copy. A pin test can only catch drift after someone writes it; not
#: having a copy cannot drift at all.
_OWN_CAVEAT_TEXT = _CaveatEnforcer.FULL_CAVEAT

#: The clause ``synthesis_length`` drops when it truncates. Everything from
#: ``"decision"`` onward is what survives, so that is the required part.
_OWN_CAVEAT_OPTIONAL_OPENING = "This summary is"


def _caveat_token_pattern(text: str) -> str:
    """Literal tokens of ``text`` joined by whitespace/commas only.

    No wildcard anywhere — that is the whole point; see above.
    """
    return r"[\s,]+".join(re.escape(word) for word in re.split(r"[\s,]+", text.strip()))


#: ``synthesis.HIGH_STAKES_NOTICE_FRAGMENT`` is still a separate literal, and
#: a test pins it equal to this one — that copy is not ours to delete here.
_OWN_CAVEAT_PATTERN = re.compile(
    r"(?:"
    + _caveat_token_pattern(_OWN_CAVEAT_OPTIONAL_OPENING)
    + r"[\s,]+)?"
    + _caveat_token_pattern(_OWN_CAVEAT_TEXT.rstrip(".").removeprefix(_OWN_CAVEAT_OPTIONAL_OPENING))
    + r"[\s,]*\.",
    re.IGNORECASE,
)


def strip_own_caveat(text: str) -> str:
    """Remove this app's own decision-support caveat sentence from ``text``.

    Can only ever delete the caveat's own words — see ``_OWN_CAVEAT_PATTERN``
    for why that is the security property and what broke when it was not.
    Everything else is returned untouched, so hostile wording next to a
    genuine caveat still reaches the scanner.

    No empty-string guard: ``re.sub`` already returns ``""`` for ``""``, and
    the caller skips falsy values anyway, so a guard here would be an
    unreachable branch dressed as defensiveness.
    """
    return _OWN_CAVEAT_PATTERN.sub(" ", text)


class WarningType(StrEnum):
    SENSITIVE_DATA = "sensitive_data"
    HIGH_STAKES = "high_stakes"


WARNING_COPY: dict[WarningType, str] = {
    WarningType.SENSITIVE_DATA: (
        "Do not include sensitive personal data, credentials, or regulated "
        "business data in your prompt. The output is logged for audit and may "
        "be reviewed by humans."
    ),
    WarningType.HIGH_STAKES: (
        "Your query mentions a high-stakes topic. The output is decision "
        "support only and is not medical, legal, financial, safety, or "
        "regulated professional advice. A human reviewer must audit it "
        "before any action."
    ),
}


class SafetyWarning(BaseModel):
    warning_type: WarningType
    version: str
    message: str
    acknowledgement_required: bool = True


class SafetyAcknowledgement(BaseModel):
    warning_type: WarningType
    version: str


@dataclass(frozen=True)
class WarningEvent:
    event_type: str
    account_id: UUID
    query_run_id: UUID | None
    warning_type: WarningType
    warning_version: str
    acknowledged: bool
    #: When an acknowledgement event aggregates several acknowledgements
    #: into a single record, the set of warning types that were
    #: acknowledged is exposed via this field. The single-acknowledgement
    #: case still uses ``warning_type`` and leaves this as an empty tuple.
    warning_types: tuple[WarningType, ...] = ()


class InMemoryWarningEventRecorder:
    MAX_EVENTS = 1024

    def __init__(self) -> None:
        self._events: list[WarningEvent] = []
        self._lock = RLock()

    def record(
        self,
        *,
        event_type: str,
        account_id: UUID,
        query_run_id: UUID | None,
        warning_type: WarningType,
        warning_version: str,
        acknowledged: bool,
        warning_types: tuple[WarningType, ...] = (),
    ) -> None:
        event = WarningEvent(
            event_type=event_type,
            account_id=account_id,
            query_run_id=query_run_id,
            warning_type=warning_type,
            warning_version=warning_version,
            acknowledged=acknowledged,
            warning_types=warning_types,
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.MAX_EVENTS:
                del self._events[: len(self._events) - self.MAX_EVENTS]
        _record_feedback_event(
            recorder="safety",
            event_type=event.event_type,
            account_id=event.account_id,
            query_run_id=event.query_run_id,
            payload=asdict(event),
        )

    def list_events(self) -> list[WarningEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class SafetyWarningPolicyService:
    """Classifies a query into the set of required warnings."""

    def required_warnings_for_query(
        self,
        query_text: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> list[SafetyWarning]:
        """Warnings a client must acknowledge before this query may run.

        ``context`` is scanned as well as ``query_text`` (issue #155): both
        of its values reach a provider prompt, so high-stakes wording placed
        there used to skip the acknowledgement. The app's own mandated
        caveat is removed first — see :func:`strip_own_caveat` for why that
        is required and why it is anchored the way it is.

        Additive: ``context=None`` reproduces the previous behaviour exactly,
        which is what every pre-#155 caller gets.
        """
        warnings: list[SafetyWarning] = [
            SafetyWarning(
                warning_type=WarningType.SENSITIVE_DATA,
                version=WARNING_VERSION,
                message=WARNING_COPY[WarningType.SENSITIVE_DATA],
                acknowledgement_required=True,
            ),
        ]
        if HIGH_STAKES_PATTERN.search(self._scannable_text(query_text, context)):
            warnings.append(
                SafetyWarning(
                    warning_type=WarningType.HIGH_STAKES,
                    version=WARNING_VERSION,
                    message=WARNING_COPY[WarningType.HIGH_STAKES],
                    acknowledgement_required=True,
                ),
            )
        return warnings

    @staticmethod
    def _scannable_text(query_text: str, context: dict[str, Any] | None) -> str:
        """The query plus every string in ``context``, minus this app's caveat.

        Scans EVERY string value rather than a hardcoded list of known keys.
        A future context field that reaches a prompt must not become a silent
        bypass just because this function predates it — the list would go
        stale without anything going red, which is the failure mode issue
        #155 exists to fix in the first place. Non-string values are skipped:
        they cannot carry wording.
        """
        if not context:
            return query_text
        parts = [query_text]
        for value in context.values():
            if isinstance(value, str) and value:
                parts.append(strip_own_caveat(value))
        return "\n".join(parts)

    def missing_acknowledgements(
        self,
        *,
        required_warnings: list[SafetyWarning],
        acknowledgements: list[SafetyAcknowledgement],
    ) -> list[SafetyWarning]:
        by_type = {ack.warning_type: ack for ack in acknowledgements}
        missing: list[SafetyWarning] = []
        for warning in required_warnings:
            ack = by_type.get(warning.warning_type)
            if ack is None or ack.version != warning.version:
                missing.append(warning)
        return missing

    def record_warning_impression(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID | None,
        warnings: list[SafetyWarning],
    ) -> None:
        for warning in warnings:
            warning_event_recorder.record(
                event_type="safety_warning_impression",
                account_id=account_id,
                query_run_id=query_run_id,
                warning_type=warning.warning_type,
                warning_version=warning.version,
                acknowledged=False,
            )

    def record_acknowledgement(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID | None,
        acknowledgements: list[SafetyAcknowledgement],
    ) -> None:
        # Record all the acknowledgements in a single event so callers can
        # see the full set of acknowledged warnings at once. The
        # ``warning_types`` field is the authoritative source for the set
        # of warning types acknowledged in this event; the ``warning_type``
        # field still records the first warning type for backwards
        # compatibility with single-acknowledgement tests.
        if not acknowledgements:
            # No acknowledgements → no event. Callers (the route layer)
            # already guard against this with the missing-acknowledgements
            # check, but downstream callers may invoke this helper
            # without that guard. We deliberately treat an empty input
            # as a no-op rather than crashing on ``acknowledgements[0]``.
            return
        warning_types = tuple(sorted({ack.warning_type for ack in acknowledgements}, key=str))
        primary = acknowledgements[0]
        warning_event_recorder.record(
            event_type="safety_acknowledgement_recorded",
            account_id=account_id,
            query_run_id=query_run_id,
            warning_type=primary.warning_type,
            warning_version=primary.version,
            acknowledged=True,
            warning_types=warning_types,
        )


warning_event_recorder = InMemoryWarningEventRecorder()
safety_warning_policy = SafetyWarningPolicyService()
