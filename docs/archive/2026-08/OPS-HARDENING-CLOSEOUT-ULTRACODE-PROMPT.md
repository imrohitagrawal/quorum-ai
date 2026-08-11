# ULTRACODE PROMPT — Ops hardening + observability deferred-item closeout (ONE PR, closes #86)

> Paste this whole file as the first message of a fresh session. It is self-contained.
> **Review is capped at TWO CYCLES total.** Each cycle may fan out multiple parallel reviewers,
> but there is never a third cycle — after cycle 2's fixes, ship on green gates.
> **Everything below lands in a SINGLE PR** (one CI gate, one deploy) — do not split.
> **Sequencing:** a sibling prompt (`OPS-NAV-GLOSSARY-FAVICON-ULTRACODE-PROMPT.md`) covers the
> `/ui/ops` UX PR. The two PRs touch disjoint surfaces, but do NOT run both sessions
> concurrently on one working tree — run this one after (or before) that one merges, or use a
> separate git worktree. Remember: a push to `main` cancels in-flight CI — land follow-ups via
> branch+PR only.

---

## 0. Context you must verify first (evidence-first — do not trust this prose)

**Run, do not assume:**

```bash
gh issue view 86 --json state,title                       # CSP hardening follow-up — expected OPEN
git log --oneline -3 origin/main
grep -n "base-uri\|form-action" src/product_app/main.py    # expected: absent from _CSP_POLICY
grep -n '"version": "0.2.0"' src/product_app/main.py       # hardcoded version in /status
grep -n "GIT_SHA\|build-arg" .github/workflows/deploy.yml  # expected: absent
sed -n '145,157p' Makefile                                 # gate-min-executed recipe
ls .github/workflows/ | grep -c error-rate                 # expected: 0 (alert rule 2 not mechanised)
curl -s https://quorum.stackclimb.com/status | jq .        # current public shape
curl -s https://quorum.stackclimb.com/ready | jq .
```

Facts established by prior sessions (re-verify cheaply above):
- `/docs` + `/openapi.json` are already gated off in prod (404) — do not touch that gate.
- `/health` `/ready` `/status` `/metrics` public is a **recorded deliberate decision (OD-1)**
  — the ops page (`ops.js`) fetches `/metrics`, `/status`, `/ready` from the browser. They
  MUST stay publicly reachable; this PR hardens content, never access.
- The `gate-min-executed` false-green mechanism is confirmed by inspection: missing XML →
  python traceback → `$$counts` empty → `set --` sets no params → `[ "" -ne 0 ]` /
  `[ "" -lt N ]` are shell *errors* that fall through as false → success echo, **exit 0**.
- Alert rule 1 (readiness-not-live) is mechanised in `availability-check.yml`; rule 2
  (5xx-rate over SLO) is documented-only in `docs/80-observability.md`.

## 1. The task — five small pieces, one PR

**A. CSP hardening (closes #86).** Add `base-uri 'none'` (or `'self'`) and
`form-action 'self'` (or `'none'` — pick from what pages actually need; verify no `<form>`
posts cross-origin) to `_CSP_POLICY` in `main.py`. This governs EVERY page — prove both
directions: the new directives are present on every route's response AND both UIs
(`/ui`, `/ui/ops`) still fully function (cross-browser e2e, not one manual look —
CSP differs per browser; `csp-smoke.yml` exists, extend it if apt).

**B. Readiness-reason leak guard.** `/ready`'s `live_readiness.reasons` must never echo raw
exception text, hostnames, key names, or stack traces. Find where reasons are produced;
assert (unit test) they are drawn from a closed enum-like set of codes/phrases. If today a
raw error string can flow in, fix the producer to map it to a code. This is
detection/validation-adjacent — key the check off the value, not whole-line substrings.

**C. `/status` recon trim.** Drop or generalize the `sentry` field (e.g. rename value to a
generic `"error_tracking": "active"` — decide once, document why). BEFORE changing shape:
`grep -rn "sentry" src/product_app/static/ tests/ e2e/` — fix every consumer and pinned
test in the same diff. `/status` is a read contract for `ops.js` and tests; do not break
the ops page's uptime/version reads.

**D. `gate-min-executed` missing-XML fix (~3 lines + bite-proof test).** Fail fast and loud
when `build/gates/$(GATE_NAME).xml` is absent (explicit file check, or propagate the python
exit status). **The test lives outside `--cov=src`'s view** — repo rule: helper/Make gate
logic needs its own test (e.g. a shell-level test invoking the target against a missing
file, asserting non-zero exit and the error message). Prove RED (current Makefile exits 0
on missing XML) then GREEN. Preserve current behaviour for present-but-failing XML.

**E. Alert rule 2 — mechanise the 5xx-rate SLO alert, $0.** New scheduled workflow modeled
on `availability-check.yml` (same tone: honest header comments, native workflow-failure
email as the alert channel):
- **Two-sample delta, no storage:** scrape `/metrics`, sleep 60–120 s, scrape again;
  5xx share of the request-count **delta** over that window; fail the job past 1%.
- **Guards (all three, tested where testable):** (1) minimum request delta before judging
  (near-zero traffic → ratio is noise → skip with a log line, exit 0); (2) negative delta
  = counter reset from a deploy → skip, don't false-alert; (3) parse defensively — a
  malformed scrape is a real failure (alert), not a silent skip.
- Put the ratio logic in a small tested script (e.g. `scripts/`), not inline YAML, so it
  gets a unit test. Update `docs/80-observability.md`: rule 2 → MECHANISED, with the same
  honest-limits note as rule 1 (GitHub auto-disables schedules after ~60 days of repo
  inactivity; failure email goes to the schedule's last-touching actor).

**F. Build-SHA passthrough.** `--build-arg GIT_SHA=${{ github.sha }}` in `deploy.yml` →
Docker `ARG`/`ENV` → surfaced as a `build_sha` field in `/status` (keep `version: 0.2.0`
as-is). Fallback `"unknown"`/`"dev"` when unset (local dev, tests). Public SHA is fine —
the repo is public; it reveals nothing GitHub doesn't. Payoff: deploy verification becomes
`curl -s https://quorum.stackclimb.com/status | jq -r .build_sha` == merged SHA — use that
in §5 and note it in the handoff so future sessions use it too.

## 2. Non-negotiable guardrails

- **`/metrics` response bytes are IMMUTABLE** (the exposition contract test must stay green).
- **Access model unchanged:** all four ops endpoints stay public (OD-1). Harden content only.
- **Never fabricate a number, label, or baseline** — the alert threshold is the documented
  1% SLO, the window is measured (log it in the job output), guards are honest skips.
- **When you loosen or suppress anything, prove both directions** (false positive gone AND
  every genuine catch still caught) — applies to B, D, and E's guards especially.
- **Hermetic / $0:** no paid API calls, no secret rotation, no paid runs. The new workflow
  hits public prod endpoints only (cheap GETs, no query-run POSTs). Scheduled cadence
  modest (e.g. every 30 min) — mirror `availability-check.yml`'s choices.
- Contract awareness: `make openapi-check` / `api-contract` exist — a `/status` shape change
  must pass them (regenerate the exported schema if that's the flow, never hand-edit drift).

## 3. Plan first, then parallelize correctly

- Short written plan (tasks → files → tests → skills) before editing; `make skill-route` where apt.
- Recon/review → parallel fan-out. **Writing → one tree-writer**; pieces A–F touch few files
  (`main.py`, `Makefile`, 2 workflow files, a script, tests, `docs/80`) — build serially in
  order **D → A → B → C → F → E** (smallest/highest-integrity first; E last since it
  depends on nothing local and needs prod curls for sanity only).

## 4. TDD discipline (RED → GREEN → prove it BITES)

Every piece has a test that fails without the change:
- A: response-header assertions for the new directives across representative routes (RED now).
- B: unit test feeding an exception-shaped reason through the producer → asserts coded output.
- C: pinned `/status` shape test updated; grep-verified consumers updated in-diff.
- D: shell-level RED→GREEN as specified above — this one is the canonical bite-proof.
- E: unit tests on the ratio script (normal, below-min-delta, negative-delta, malformed input).
- F: `/status` includes `build_sha` with env set, `"unknown"` without.
Run any timing-sensitive addition N≥10×; `make validate && make quality` green.

## 5. Ship & deploy verification (truth = the job ran, not `/health` 200)

- ONE PR, merged after the review cycles. **Confirm the deploy JOB actually ran**
  (`success`, not `skipped`/`cancelled`) — `gh run list --branch main` + filter
  `startsWith(SHA)` (`--commit` silently returns `[]`).
- **Verify prod by content:**
  ```bash
  curl -sI https://quorum.stackclimb.com/ui/ops | grep -i "content-security-policy" | grep -c "base-uri"   # >0
  curl -s https://quorum.stackclimb.com/status | jq -r .build_sha    # == merged SHA (piece F proves itself)
  curl -s https://quorum.stackclimb.com/status | jq 'has("sentry")'  # false after C
  ```
- Trigger the new alert workflow once via `workflow_dispatch` and confirm a green run on
  real prod data (and that a below-min-delta window skips honestly, if that's what occurs).

## 6. Review — MAX TWO CYCLES, then ship

**Cycle 1 (parallel fan-out on the staged diff):**
1. **Breaker** — primary lens for this PR: attack the CSP change (does any page break? any
   directive weaker than intended?), the reason-code mapping (can raw text still leak?),
   the gate fix (any path still exiting 0 wrongly?), the alert guards (can a real outage be
   mis-skipped as low-traffic? can a reset mask a real spike?). Default "refuted" unless
   demonstrated.
2. **Correctness reviewer** — `/status` consumers all updated; openapi/contract artifacts
   regenerated not hand-drifted; workflow YAML actually valid (actionlint if available);
   docs/80 matches the mechanised reality; tests genuinely bite.

Verify findings before acting; fix real ones.
**Cycle 2 (fresh eyes, fixed diff only).** Fix what survives. **Stop — no cycle 3**;
leftovers become follow-up notes.

## 7. Definition of done

- [ ] Real state verified up front (§0), not assumed.
- [ ] A: `base-uri` + `form-action` live on every route; both UIs verified cross-browser; #86 closed by the PR.
- [ ] B: reasons provably enum-coded; leak test RED-proven.
- [ ] C: `sentry` field trimmed/generalized; every consumer + pinned test updated in-diff; ops page unbroken.
- [ ] D: gate fails loudly on missing XML; shell-level RED→GREEN shown; present-XML behaviour unchanged.
- [ ] E: rule-2 workflow live with all three guards, script unit-tested, one green dispatch run on prod; docs/80 says MECHANISED with honest limits.
- [ ] F: `build_sha` in `/status` == deployed SHA on prod; fallback tested; handoff notes the new one-line deploy check.
- [ ] `/metrics` bytes unchanged; endpoints still public; `make validate`/`quality`/contract gates green.
- [ ] Exactly ≤2 review cycles; findings verified then fixed.
- [ ] ONE PR merged; **deploy job confirmed run**; prod verified by content (§5).
- [ ] `docs/00-factory-console.md` + `docs/session-handoff.md` + RESULT ledger updated; `make handoff` run.
