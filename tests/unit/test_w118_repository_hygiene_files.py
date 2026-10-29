"""W118 and W79: the repository's ownership, update and disclosure files are real.

Red when: ``.github/CODEOWNERS`` holds a placeholder owner or loses its
catch-all rule; ``.github/dependabot.yml`` misses a lock file the tree has (the
root ``uv.lock``, a tracked ``package-lock.json``, or the workflows folder), or
an entry stops being monthly, grouped to minor and patch updates, with
majors ignored and a 7-day cooldown; ``SECURITY.md`` stops pointing at this
repository's private vulnerability report form; a setting that
``src/product_app/config.py`` hides from ``repr`` or types as ``SecretStr`` (a
secret), or a ``secrets.*`` a workflow reads, is missing from the "Replacing a
secret" table of ``docs/84-incident-response.md``; or a ``src/`` file that
names ``QUORUM_TOKEN_SECRET`` in code is not cited in that secret's row.
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

#: It asks git and reads root files, so it cannot run inside mutmut's copy
#: (ADR-0183); it tests repository files, not ``src/``, so nothing is lost.
pytestmark = pytest.mark.repo_introspection

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
            assert re.fullmatch(r"@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:/[\w.-]+)?", owner), (
                owner
            )


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


def test_every_dependabot_entry_is_monthly_grouped_and_waits_seven_days() -> None:
    for update in _updates():
        name = update["package-ecosystem"]
        assert update["schedule"]["interval"] == "monthly", name
        groups = update["groups"]
        assert len(groups) == 1, name
        group = next(iter(groups.values()))
        assert group["patterns"] == ["*"], name
        assert group["update-types"] == ["minor", "patch"], name
        assert update["cooldown"]["default-days"] == 7, name
        assert {"dependency-name": "*", "update-types": ["version-update:semver-major"]} in update[
            "ignore"
        ], name


def test_security_policy_points_at_the_private_report_form() -> None:
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "https://github.com/imrohitagrawal/quorum-ai/security/advisories/new" in text


def _hidden_settings() -> set[str]:
    tree = ast.parse((ROOT / "src" / "product_app" / "config.py").read_text(encoding="utf-8"))
    settings = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
    hidden = set()
    for node in settings.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.value, ast.Call):
            if "SecretStr" in ast.unparse(node.annotation) and isinstance(node.target, ast.Name):
                hidden.add(node.target.id)
            continue
        annotation = ast.unparse(node.annotation)
        if "SecretStr" in annotation and isinstance(node.target, ast.Name):
            hidden.add(node.target.id)
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


def _table_row(name: str) -> str:
    text = (ROOT / "docs" / "84-incident-response.md").read_text(encoding="utf-8")
    section = text.split("## Replacing a secret", 1)[1]
    rows = [line for line in section.splitlines() if line.startswith(f"| `{name}` |")]
    assert len(rows) == 1, (name, rows)
    return rows[0]


def _src_files_naming(name: str) -> set[str]:
    found = set()
    for path in sorted((ROOT / "src" / "product_app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.Constant) and n.value == name for n in ast.walk(tree)):
            found.add(path.name)
    return found


def test_the_token_secret_row_cites_every_file_that_reads_it() -> None:
    files = _src_files_naming("QUORUM_TOKEN_SECRET")
    # Partner: the secret is read in code today, by more than one module.
    assert {"config.py", "session_store.py"} <= files, files
    row = _table_row("QUORUM_TOKEN_SECRET")
    assert not {f for f in files if f not in row}, files


def test_every_workflow_secret_has_replacement_steps() -> None:
    names = set()
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        names |= set(
            re.findall(r"secrets\.([A-Z][A-Z0-9_]+)", workflow.read_text(encoding="utf-8"))
        )
    names.discard("GITHUB_TOKEN")
    # Partner: the deploy token is read by a workflow today.
    assert "FLY_API_TOKEN" in names, names
    assert names <= _replacement_table_names(), names - _replacement_table_names()
