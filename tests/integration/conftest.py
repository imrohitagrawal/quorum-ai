"""Fixtures shared across integration test modules.

``sign_in`` (a Google sign-in against the loopback token stub) is defined in
``test_google_sign_in.py``; re-exported here so the W7 history tests
(``test_account_history_flow.py``) can request it by name.
"""

from tests.integration.test_google_sign_in import sign_in  # noqa: F401

__all__ = ["sign_in"]
