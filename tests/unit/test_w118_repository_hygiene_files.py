"""W118 and W79: the repository's ownership, update and disclosure files are real.

Red when: ``.github/CODEOWNERS`` holds a placeholder owner or loses its
catch-all rule; ``.github/dependabot.yml`` misses a lock file the tree has (the
root ``uv.lock``, a tracked ``package-lock.json``, or the workflows folder), or
an entry loses its group or cooldown; ``SECURITY.md`` stops pointing at this
repository's private vulnerability report form; or a setting that
``src/product_app/config.py`` hides from ``repr`` (a secret) is missing from the
"Replacing a secret" table of ``docs/84-incident-response.md``.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

#: Hidden settings that are not credentials, each with the reason.
NOT_A_SECRET = {
    "session_cap_exempt_networks": "a list of networks, hidden because it names testers' addresses",
}


def _tracked(pattern: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", pattern], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def test_codeowners_names_a_real_owner_for_every_path() -> None:
    lines = [
        line.split()
        for line in (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines, "CODEOWNERS has no rule"
    assert any(parts[0] == "*" for parts in lines), lines
    for parts in lines:
        owners = parts[1:]
        assert owners, parts
        for owner in owners:
            assert re.fullmatch(r"@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:/[\w.-]+)?", owner), owner


def _updates() -> list[dict[str, Any]]:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert config["version"] == 2
    updates: list[dict[str, Any]] = config["updates"]
    return updates


def _expected_entries() -> set[tuple[str, str]]:
    expected = set()
    if (ROOT / "uv.lock").is_file():
        expected.add(("uv", "/"))
    for lock in _tracked("package-lock.json") + _tracked("*/package-lock.json"):
        folder = str(Path(lock).parent)
        expected.add(("npm", "/" if folder == "." else "/" + folder))
    if _tracked(".github/workflows/*.yml"):
        expected.add(("github-actions", "/"))
    return expected


def test_dependabot_covers_every_lock_file_in_the_tree() -> None:
    expected = _expected_entries()
    # Partner: the tree really has the three kinds of lock file today.
    assert {kind for kind, _ in expected} == {"uv", "npm", "github-actions"}, expected
    present = {(u["package-ecosystem"], u["directory"]) for u in _updates()}
    assert expected <= present, expected - present


@pytest.mark.parametrize("field", ["groups", "cooldown"])
def test_every_dependabot_entry_is_grouped_and_waits(field: str) -> None:
    for update in _updates():
        assert update.get(field), (update["package-ecosystem"], field)


def test_security_policy_points_at_the_private_report_form() -> None:
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "https://github.com/imrohitagrawal/quorum-ai/security/advisories/new" in text


def _hidden_settings() -> set[str]:
    tree = ast.parse((ROOT / "src" / "product_app" / "config.py").read_text(encoding="utf-8"))
    settings = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
    hidden = set()
    for node in settings.body:
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call)):
            continue
        for keyword in node.value.keywords:
            if (
                keyword.arg == "repr"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
                and isinstance(node.target, ast.Name)
            ):
                hidden.add(node.target.id)
    return hidden


def _replacement_table_names() -> set[str]:
    text = (ROOT / "docs" / "84-incident-response.md").read_text(encoding="utf-8")
    section = text.split("## Replacing a secret", 1)[1]
    return set(re.findall(r"^\| `([A-Z][A-Z0-9_]+)` \|", section, flags=re.MULTILINE))


def test_every_secret_setting_has_replacement_steps() -> None:
    hidden = _hidden_settings()
    # Partner: the parser finds the secrets that exist today.
    assert {"openrouter_api_key", "google_oauth_client_secret", "sentry_dsn"} <= hidden, hidden
    names = _replacement_table_names()
    missing = {h for h in hidden - set(NOT_A_SECRET) if h.upper() not in names}
    assert not missing, missing
    # A stale exemption is itself a fault: it names a hidden setting that exists.
    assert set(NOT_A_SECRET) <= hidden, set(NOT_A_SECRET) - hidden
