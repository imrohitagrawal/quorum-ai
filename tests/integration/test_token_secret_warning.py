"""C13: the cost estimator warns when QUORUM_TOKEN_SECRET is unset.

When the binding secret is auto-generated, every restart rotates
it. Outstanding confirmation tokens become unverifiable, and a
multi-instance deployment would generate inconsistent tokens. The
warning surfaces the misconfiguration at startup instead of
silently degrading behaviour later.
"""

from __future__ import annotations

import warnings

import pytest


def test_warning_emitted_when_secret_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing ``CostEstimationService`` without an env-supplied
    or call-supplied secret emits a warning.
    """
    monkeypatch.delenv("QUORUM_TOKEN_SECRET", raising=False)
    from product_app.costs import CostEstimationService

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        CostEstimationService()

    messages = [str(w.message) for w in caught]
    assert any("QUORUM_TOKEN_SECRET" in m for m in messages), (
        f"expected warning about QUORUM_TOKEN_SECRET; got {messages}"
    )


def test_no_warning_when_env_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``QUORUM_TOKEN_SECRET`` is set in the environment, no
    warning fires — the configuration is correct.
    """
    monkeypatch.setenv("QUORUM_TOKEN_SECRET", "test-secret-from-env")
    from product_app.costs import CostEstimationService

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        CostEstimationService()

    assert not any("QUORUM_TOKEN_SECRET" in str(w.message) for w in caught), (
        "warning fired even though the secret was set"
    )


def test_no_warning_when_binding_secret_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the caller passes ``binding_secret=`` explicitly, no
    warning fires — the caller is opting in to the explicit value.
    """
    monkeypatch.delenv("QUORUM_TOKEN_SECRET", raising=False)
    from product_app.costs import CostEstimationService

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        CostEstimationService(binding_secret="explicit-test-secret")

    assert not any("QUORUM_TOKEN_SECRET" in str(w.message) for w in caught)
