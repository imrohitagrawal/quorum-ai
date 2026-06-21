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
from uuid import UUID

from pydantic import BaseModel

from product_app.feedback_store import record_event as _record_feedback_event

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

    def required_warnings_for_query(self, query_text: str) -> list[SafetyWarning]:
        warnings: list[SafetyWarning] = [
            SafetyWarning(
                warning_type=WarningType.SENSITIVE_DATA,
                version=WARNING_VERSION,
                message=WARNING_COPY[WarningType.SENSITIVE_DATA],
                acknowledgement_required=True,
            ),
        ]
        if HIGH_STAKES_PATTERN.search(query_text):
            warnings.append(
                SafetyWarning(
                    warning_type=WarningType.HIGH_STAKES,
                    version=WARNING_VERSION,
                    message=WARNING_COPY[WarningType.HIGH_STAKES],
                    acknowledgement_required=True,
                ),
            )
        return warnings

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
