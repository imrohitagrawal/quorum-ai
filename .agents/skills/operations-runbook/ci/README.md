# Wiring the documentation verifier into CI (docs-as-code, in lockstep)

The house style asks for docs sourced in the repository, versioned in Git, and checked by a gate
that fails when a document drifts. These files provide that gate. Replace the two placeholders to
match the skill you are using:

| Skill | `<DOCS_PATH>` | `<FORMAT>` | `--skill <SKILL_NAME>` |
|---|---|---|---|
| learning-track | `docs/learning` | `md` | `learning-track` |
| architecture-and-decisions | `docs/architecture` | `md` | `architecture-and-decisions` |
| project-faq | `outputs/<project>-faq.html` | `html` | `project-faq` |
| usage-guide | `docs/usage-guide.md` | `md` | `usage-guide` |
| operations-runbook | `docs/runbook.md` | `md` | `operations-runbook` |
| onboarding-companion | `docs/onboarding` | `md` | `onboarding-companion` |

The `--skill` name resolves the reading-grade target and the scope from `docs/project-profile.md`,
so those values live in one place. A `--grade-target` / `--scope` flag still overrides if needed.
PyYAML must be installed for the profile to be read — otherwise scope silently defaults to `public`
and an internal set is mis-judged. Both templates install / declare it.

`--license LICENSE` confirms the repository's LICENSE carries the "AS IS" warranty/liability
disclaimer and names the content licence (it warns if the separate code licence is unnamed). Point it
at the real LICENSE path; drop the flag only if the repo has no LICENSE yet.

- **`.pre-commit-config.yaml`** — runs the verifier locally before a commit lands. Install once with
  `pip install pre-commit && pre-commit install`.
- **`verify-docs.yml`** — a GitHub Actions workflow. Copy it to `.github/workflows/verify-docs.yml`.
