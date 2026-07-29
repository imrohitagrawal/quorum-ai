# CI/CD Plan

## Gates

- Validate docs
- Format check
- Lint
- Type check
- Report-generating pytest with JUnit XML and coverage XML
- Deterministic repository security scan
- Docker image build
- Non-secret release evidence artifact upload

## Artifact Evidence

The VS-013 local and CI evidence path is:

- `make test-report` writes `build/test-results/pytest.xml` and `build/coverage/coverage.xml`.
- `make security-scan` writes `build/security/security-scan.json`.
- `make ci-evidence` runs both evidence targets locally.
- `.github/workflows/ci.yml` uploads those files as the `release-hardening-evidence` artifact.

Remote CI evidence is not claimed until GitHub Actions runs and the uploaded artifact is retained.

## Pull request template — what it is, and what it is not

`.github/pull_request_template.md` prefills every new pull request's body.

**It is not enforcement.** GitHub has no required-field mechanism for pull
requests — issue templates support forms, pull request templates do not
([GitHub docs on templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates);
confirmed in [community discussion #84771](https://github.com/orgs/community/discussions/84771),
where the stated workaround is a workflow that reads the body and fails a
check). Nothing today parses pull request bodies in this repo, so the template
sits **above the line** in `docs/DAY-ONE-PROMPT.md` §1: influence, not a gate.
It is recorded here so nobody later reads it as one.

**Why it asks for pasted evidence instead of checkboxes.** The template is
designed against this repository's own measured failure history
(`docs/metrics/mutation-gate-study.md` §8, `docs/103-incident-learnings.md`),
not against a generic checklist. The four recurring failures — claims from
reading rather than running, tests that pass whether or not the feature works,
advisory gates believed without opening the log, numbers written into prose
unmeasured — share one property: **a checkbox cannot detect any of them.** Each
would have been ticked honestly by someone who believed the claim. So every
field asks for a command, a number, or a line that was broken.

Design taken from reading eight real templates in full:

| Read | Taken |
|---|---|
| [kubernetes/kubernetes](https://raw.githubusercontent.com/kubernetes/kubernetes/master/.github/PULL_REQUEST_TEMPLATE.md) | Prose headings and fenced blocks, **zero checkboxes**; every field has a defined "nothing" value (`NONE`, `N/A`) so blank is distinguishable from skipped. This is the structural model. |
| [pandas-dev/pandas](https://raw.githubusercontent.com/pandas-dev/pandas/main/.github/PULL_REQUEST_TEMPLATE.md) | Link each requirement to the doc that defines it, so the ask is an instruction rather than a claim. |
| [angular/angular](https://raw.githubusercontent.com/angular/angular/main/.github/PULL_REQUEST_TEMPLATE.md) | The before/after pair ("current behavior" / "new behavior") yields a claim a reviewer can test. |
| [Microsoft Engineering Playbook](https://microsoft.github.io/code-with-engineering-playbook/code-reviews/pull-request-template/) | The only one asking for artefacts — logs, outputs — rather than assent. Directly targets our failure mode (d). |

Read and **rejected**, with the reason:

| Read | Rejected |
|---|---|
| [home-assistant/core](https://raw.githubusercontent.com/home-assistant/core/dev/.github/PULL_REQUEST_TEMPLATE.md) (~13 boxes) | "Tests added and passed" as one box is precisely the claim our history says is unreliable — it is satisfied by a test that passes with the feature deleted. Split into test identity, bite proof, and run output. Its `DO NOT DELETE ANY TEXT` header is evidence the template is too long to survive contact. |
| [electron/electron](https://raw.githubusercontent.com/electron/electron/main/.github/PULL_REQUEST_TEMPLATE.md), [symfony/symfony](https://raw.githubusercontent.com/symfony/symfony/7.4/.github/PULL_REQUEST_TEMPLATE.md) | "All checks passed" as a checkbox encodes the exact #158 defect — a gate believed without opening its log. Replaced with the job log link and the number the job printed. |
| [rust-lang/rust](https://raw.githubusercontent.com/rust-lang/rust/master/.github/pull_request_template.md), [apache/airflow](https://raw.githubusercontent.com/apache/airflow/main/.github/PULL_REQUEST_TEMPLATE.md) | Near-empty templates work because the rigour lives in bots. That is the right destination, not the right starting point for a repo whose problem is unverified claims. |
| Angular's 9-way and Home Assistant's 7-way type taxonomies | Those serve triage at high pull request volume. A single-maintainer repo pays the attention cost for no signal. |

**Length.** Five sections, all prose or fenced blocks, no checkboxes. Measured
across the eight templates read, the median is ~7 interactive items and the two
highest-traffic projects (kubernetes, rust) have the fewest. Zhang et al.,
*"Consistent or not? An investigation of using Pull Request Template in
GitHub"*, Information and Software Technology, 2021
([abstract](https://www.sciencedirect.com/science/article/abs/pii/S0950584921002354))
reports that only 1.2% of ~538k sampled projects use a template at all, and
that surveyed contributors accept templates asking for *pivotal* information —
description, test, checklist. **Caveat, stated because it is the rule here:
that paper is behind a paywall and was read as a search-result abstract, not in
full. Treat its numbers as second-hand.**

**Promotion condition.** This template becomes enforcement only if a workflow
parses the body and fails a check on an empty evidence section. That is not
built, and should not be built until someone measures how many recent pull
requests it would have failed — the same replay rule every other gate here is
held to (`docs/DAY-ONE-PROMPT.md` §4a-bis).

## Branch protection on `main` (#61)

`main` is a protected branch. Changes land only through a pull request; direct
pushes are rejected (including for docs and including for admins). This closes the
concurrency race behind the 2026-07-22 undeploy churn: a follow-up direct push
could cancel a just-merged commit's in-flight CI (`docs/103-incident-learnings.md`).

Enforced configuration (GitHub → Settings → Branches, or the REST protection API):

- **Require a pull request before merging.** No direct `git push origin main`.
- **Require branches be up to date before merging** (`strict: true`), so a merge
  cannot race a just-merged commit's CI.
- **Require these status checks to pass** — names must match the check runs CI
  actually reports (verified against a real commit, not the issue text):
  - `validate-and-test`
  - `pytest (Python 3.12)`
  - `Changed-lines coverage >= 95% (blocking)`
  - `Schemathesis API contract (blocking)`
  - `FR traceability completeness (blocking)`
  - `e2e axe + parity (chromium)`
- **Include administrators** (`enforce_admins: true`) — the incident's trigger was
  an admin's direct docs push, so admins are bound too. Advisory checks
  (`Mutation score`, `Hermetic perf`, `codex-review`) are intentionally **not**
  required so they cannot block a merge.

Inspect / re-apply:

```bash
gh api repos/:owner/:repo/branches/main/protection \
  -q '{strict: .required_status_checks.strict, checks: .required_status_checks.contexts, admins: .enforce_admins.enabled}'
```

## Canonical domain: `quorum.stackclimb.com` (2026-07-22)

The app's canonical public URL is **https://quorum.stackclimb.com** (UI at
**`/ui`**). This is a **custom domain in front of the same Fly.io app** — the
runtime did *not* move off Fly.io. `quorum-ai.fly.dev` (Fly's default hostname)
continues to serve the identical app and is retained as a fallback.

**Why a custom domain, not a move:** `*.fly.dev` is only Fly's default hostname,
not a separate host. Pointing a `stackclimb.com` subdomain at the running app is
DNS + TLS, not a migration — matching how the other stackclimb.com products are
fronted. No redeploy of the app was required.

**Setup steps (reproducible / for rebuild):**

1. **Fly cert** — register the hostname so Fly provisions a Let's Encrypt cert:
   ```bash
   fly certs add quorum.stackclimb.com -a quorum-ai
   fly certs setup quorum.stackclimb.com -a quorum-ai   # prints exact DNS records
   ```
2. **Cloudflare DNS** (stackclimb.com zone) — add two records, both **grey-cloud
   (DNS only)**, pointing straight at the app's Fly IPs:
   - `A     quorum → 66.241.125.57`
   - `AAAA  quorum → 2a09:8280:1::131:de60:0`

   Grey-cloud is **required**: an orange-cloud (proxied) record makes Cloudflare
   intercept Let's Encrypt's challenge and the cert never validates. A/AAAA direct
   to Fly also proves ownership, so **no `_fly-ownership` TXT is needed** with this
   layout. (A CNAME-only or proxied setup *would* need the TXT.)
3. **Validate** — `fly certs check quorum.stackclimb.com` flips to `Issued`
   (1–5 min after DNS propagates).

**Verified end-state (2026-07-22):** `/health` 200 with valid TLS, `/ready`
`state: live`, HTTP→HTTPS 301, `/ui` 200 (HTML), CSP/HSTS/`X-Frame-Options`
present, and responses byte-identical to `quorum-ai.fly.dev`.

**Code touch-points:** the app needed **no** code change to work on the new domain
— the CSP is `self`-relative (`src/product_app/main.py`) and there is no
`CORSMiddleware`/`ALLOWED_HOSTS` host pinning, so it is domain-agnostic. Two
attribution strings were updated to the canonical URL (OpenRouter dashboard
labelling only, no functional impact): `OPENROUTER_APP_URL` (`fly.toml`) and the
`HTTP-Referer` header (`src/product_app/feedback_audit.py`).

**Deliberately unchanged:** the post-deploy health checks in
`.github/workflows/deploy.yml` and `deploy-drift-watchdog.yml` stay on
`quorum-ai.fly.dev`. They test the Fly origin directly and must stay decoupled
from Cloudflare/DNS, so a CDN or DNS hiccup can never fail a deploy gate for a
reason unrelated to the deploy.
