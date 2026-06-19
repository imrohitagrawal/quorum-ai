"""Compatibility shim for Starlette's test client import path.

Starlette 1.3.x prefers ``httpx2`` and emits a deprecation warning when it
falls back to ``httpx``. The project already depends on ``httpx`` for tests, so
this local shim re-exports the installed package under the expected name and
keeps pytest output warning-free.
"""

from httpx import *  # noqa: F401,F403
from httpx import _client as _client  # noqa: F401
from httpx import _types as _types  # noqa: F401
