from product_app.safety import (
    WARNING_COPY,
    WARNING_VERSION,
    SafetyAcknowledgement,
    WarningType,
    safety_warning_policy,
)


def test_sensitive_data_warning_is_always_required() -> None:
    warnings = safety_warning_policy.required_warnings_for_query("Compare these options")

    assert [warning.warning_type for warning in warnings] == [WarningType.SENSITIVE_DATA]
    assert warnings[0].version == WARNING_VERSION
    assert "Do not include sensitive" in warnings[0].message


def test_high_stakes_topics_require_decision_support_warning() -> None:
    examples = [
        "Should I use this medical diagnosis?",
        "Review this legal contract",
        "Is this investment financially safe?",
        "Assess this safety hazard",
        "Does this regulated compliance plan work?",
    ]

    for example in examples:
        warnings = safety_warning_policy.required_warnings_for_query(example)
        warning_types = {warning.warning_type for warning in warnings}
        assert WarningType.HIGH_STAKES in warning_types


def test_missing_acknowledgements_returns_unacknowledged_warnings() -> None:
    required_warnings = safety_warning_policy.required_warnings_for_query(
        "Review this legal contract",
    )

    missing = safety_warning_policy.missing_acknowledgements(
        required_warnings=required_warnings,
        acknowledgements=[
            SafetyAcknowledgement(
                warning_type=WarningType.SENSITIVE_DATA,
                version=WARNING_VERSION,
            ),
        ],
    )

    assert [warning.warning_type for warning in missing] == [WarningType.HIGH_STAKES]


def test_warning_copy_does_not_claim_sensitive_data_is_safe() -> None:
    combined_copy = " ".join(WARNING_COPY.values()).casefold()

    forbidden_claims = [
        "safe for secrets",
        "safe for regulated personal data",
        "safe for confidential business data",
        "guaranteed private",
    ]
    for claim in forbidden_claims:
        assert claim not in combined_copy
