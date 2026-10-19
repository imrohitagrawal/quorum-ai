# Session prompt: security fixes, and the board rows W85, W86, W100, W87, W88, W80, W75 and W76

Written by the session of 2026-10-17 (transcript `21387da6`). This file is
the session's wording. The owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/2026-10-17-session-handoff*.md`.
2. `docs/65-open-work.md`: rows W85, W86, W100, W87, W88, W80, W75 and W76, and the Parked table
   (`make parked-check`).
3. `docs/19-change-control-log.md`: CHG-049, CHG-055, CHG-056, CHG-058, CHG-059, CHG-060,
   CHG-061 and CHG-062.
4. `docs/analysis/2026-10-17-w82-security-baseline.md` (sections 4 and 5) and
   `docs/41-security-controls.md`. The public text holds back how to reproduce the live gaps W85,
   W87, W88 and W100 (CHG-060). The full evidence is outside the repository, in
   `~/Projects/quorum-ai-evidence/2026-10-17/w82/` (the documents before the hold-back are in its
   `full-detail-docs/`). Those copies predate CHG-060 and CHG-061 (their change log ends at
   CHG-059), so when a fix ships, restore its detail hunk by hunk; never copy a file back whole.
   The W85 probe is `w85-probe.py` in the same folder.
5. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`. A second session may be
   researching W28 at the same time: it takes CHG numbers from CHG-075 and ADR numbers from
   ADR-0180, so this session takes CHG-063 to CHG-074 and ADR-0171 to ADR-0179. Both sessions
   append to `docs/19-change-control-log.md` and `docs/65-open-work.md`, and both regenerate
   `docs/session-handoff.md` and `docs/product-readiness.md`: merge `main` in before starting and
   again before each push. One session's merge can cancel the other's deploy, so check production by ancestry: `/status` `build_sha` must be a commit that contains your merge
   (`git merge-base --is-ancestor <your merge> <build_sha>` exits 0), not only equal to it.

**Ask the owner first, in one batch** (at most four questions per call; each with a concrete example
and a recommendation): for W80, who may read `/feedback/audit` (an operator credential, or remove the
route); for W85, the size limit on a request body; for W88, what happens to a request whose browser
does not say where it came from (allow or refuse); for W87, the form of the operator command and how
the single-factor sign-in is recorded; and any new words the page will show.

## The items, in order

Each is its own pull request, deployed and checked live before the next starts. Route each
with `make skill-route ITEM=<row>`. This is the owner's order (CHG-061).

1. **W85.** Reproduce first from the private evidence. The change is in the request handling of
   `src/product_app/main.py` and the request models in `src/product_app/query_runs.py`.
2. **W86.** `src/product_app/session_store.py`.
3. **W100.** `src/product_app/static/app.js`: a page change, so the browser lanes (AGENTS.md rule
   13), the user-journey tester and the owner's approval of any new words apply.
4. **W87.** The owner's values are in CHG-056 (c) and (d). `src/product_app/auth.py`,
   `session_store.py`, `account_deletion.py` and `google_signin.py`, and the page for the
   sign-in-again step: a page change too.
5. **W88.** The session-opening code in `src/product_app/main.py`, and `auth.py`.
6. **W80.** Two tests assert today's behaviour and must change with the fix
   (`docs/41-security-controls.md`, "Measures no test would miss").
7. **W75**, with the additions the row names.
8. **W76.** Its parts are agents' reports: reproduce each first.

The public rows of W85, W87, W88 and W100 name few files, so `make skill-route ITEM=<row>` sees
little: route each again with `make skill-route DIFF=origin/main` once its change exists.

For every fix, update the measure's row in `docs/41-security-controls.md` (its Proof and Status)
and the item's rows in `docs/analysis/2026-10-17-asvs-5-level-2-check.md`. A new measure takes the
next SC number, and the pinned id list in `tests/unit/test_security_controls_cite_real_tests.py`
changes with it. W75 changes
`tests/integration/test_security_headers.py::test_security_headers_present_on_every_response`,
which pins `'unsafe-inline'`. Every decorated function in `src/product_app/` counts toward a cap
of 55, and the count is 55 today (`tests/unit/test_mutation_test_set_integrity.py`): a new route
uses `add_api_route`, and a new validator needs another form or a reviewed raise of the cap.

When a row in CHG-060's list (W85, W87, W88, W100) ships, its pull request may restore the
held-back detail to the public documents. W28 follows these eight, in a fresh session (CHG-061);
the W28 research session writes that session's prompt.

## Approvals

Sending this prompt approves the following for one pull request per item above, and the
end-of-session handoff (docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""` (or the issues it closes).
- Deploy.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is allowed:
- no paid call;
- no `fly secrets` change;
- no change to GitHub's repository settings;
- no attack on production;
- no W28 code and no W28 decision recorded (another session researches W28);
- no work on rows outside the list above; a serious new gap goes on the board for the owner.

## End of session

1. Write the narrative handoff. Every "merged" or "in production" must cite its pull request.
2. Write the next session's prompt from `.agents/skills/work-item-delivery/prompt-template.md`.
3. In the handoff pull request, move this file into `docs/archive/YYYY-MM/` (run `ls` there first;
   add a date suffix if the name exists) and commit the next prompt at the root.
4. Run `make handoff` last. It prints the line for the owner to paste; end the closing status block
   with that line under "Next action".
