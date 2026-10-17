# Session prompt: bring-your-own key research, and the board row W28

Written by the session of 2026-10-17 (transcript `21387da6`). This file is
the session's wording. The owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/2026-10-17-session-handoff*.md`.
2. `docs/65-open-work.md`: row W28 and its line in the Parked table (`make parked-check`).
3. `docs/19-change-control-log.md`: CHG-011 (D8, bring-your-own key, planned and not decided),
   CHG-012 (D8's timing, superseded), CHG-026 (f), CHG-051 (its order is superseded), CHG-055,
   CHG-059 (decision 3 decided; decisions 1, 2 and 4 reopened), CHG-060, CHG-061 (the current
   order) and CHG-062 (one source of truth for W28; complete prompts).
4. **Four input files gathered on 2026-10-17, outside the repository:**
   `~/Projects/quorum-ai-evidence/2026-10-17/w28-inputs/`. They are agents' reports, not yet
   reviewed: treat every claim as a lead and check it before you use it.
   - `w28-inventory-repo.md`: every W28 trace in the repository. The owner's words (13 in the
     repository; 6 messages only in transcripts, 4 of them about BYOK's design; CHG-062 now quotes one
     of the other two), the decisions and which are superseded, every document
     with its status and its false claims, the requirement conflicts, the code and tests that
     touch keys, the build constraints, and the gaps.
   - `w28-inventory-github.md`: issues, pull requests, branches and git history.
   - `w28-research-brief.md`: the checklist the research must cover. Standards, storage
     patterns, how other products handle users' keys, operations, and failure modes of a
     one-machine Fly app, each with a source or an UNVERIFIED mark.
   - `key-safety-tests-2026-10-13.md`: the key-safety test designer's report of 2026-10-13, taken
     from that session's transcript. It holds the 21 tests a key must pass; section 5 of the
     2026-10-13 review gives only their five subjects.
5. **The earlier W28 work, to build on rather than repeat:**
   - the plan on the parked branch `w28/byok-pr1-plan` (draft pull request #525), the branch's
     only new file: `git show --stat origin/w28/byok-pr1-plan` names it, and
     `git show origin/w28/byok-pr1-plan:<that path>` prints it. One line is out
     of date: "no encryption exists" (`cryptography` has been a dependency since #551, where the PDF
     reader uses it to open encrypted PDFs; no code under `src/` imports it);
   - the raw map behind that plan, outside the repository:
     `~/Projects/quorum-ai-evidence/2026-09-29/workflow-reports/byok-pr1-map-wf_aedbee72-7a1.md`.
     Nothing in the repository links to it, and it holds findings found nowhere else (see item 1);
   - `docs/analysis/2026-09-23-byok-failure-modes.md`;
   - `docs/analysis/2026-10-16-w28-decision-research.md`;
   - section 5 of `docs/analysis/2026-10-13-security-review.md` (its 21 tests are in
     `key-safety-tests-2026-10-13.md` above); section 3 of `docs/analysis/2026-10-17-w82-security-baseline.md`; ADR-0121.
6. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`. Another session builds the
   security rows at the same time: take CHG numbers from CHG-075 and ADR numbers from ADR-0180, and
   touch neither `docs/41-security-controls.md` nor rows W71 to W101 on the board. Merge `main`
   into your branch before starting and again before pushing: both sessions append to
   `docs/19-change-control-log.md` and `docs/65-open-work.md`, and both regenerate
   `docs/session-handoff.md` and `docs/product-readiness.md`. One session's merge can cancel the
   other's deploy, so check production by ancestry: `/status` `build_sha` must be a commit that contains your merge
   (`git merge-base --is-ancestor <your merge> <build_sha>` exits 0), not only equal to it.

## The owner's words that bind this work

Checked word for word against the transcripts on 2026-10-17. The first four are in no CHG row yet.
- 2026-09-23 16:11:37Z (transcript `23fee4a3`): with the user's own key, live answers and the judge
  should be on by default; *"It should not need fly secrets settings."*; *"the per-IP limitations,
  the per-day charges, or per-run-per-day charges should not be enforced from the code side. It
  should be something that the user should be able to select. For example, we can have a $5 window
  or a limit"*.
- 2026-09-23 16:17:23Z (`23fee4a3`): *"the quorum-ai judge API key should also be the same as the
  bring your own key which the user is providing as an open router key"*.
- 2026-09-23 16:21:02Z (`23fee4a3`): *"For the rest, I agree with all your suggestions"*: the rails
  table ADR-0121 records.
- 2026-10-13 06:18:27Z (`20d36bac`): the key must be stored so that *"it is not leaked, is not in
  the sessions, and is not being hunted by any attackers or stealers"*.
- 2026-09-29 (M03 point 5, `docs/analysis/2026-09-29/OWNER-DISCUSSION-LOG.md:111`): *"We should
  ensure that we are not storing it in any logs, any web sessions, or anywhere the user or an
  attacker can web-inspect and see the keys, and that any other security threats are not there."*
- 2026-10-17 (CHG-059): enterprise practice; no re-paste of the key after every stop and deploy;
  thorough research; decision 3 decided: signed-in only.

**Tensions to settle with the owner, not by assumption:**
- "Not in the sessions" (2026-10-13) against a key held per browser session (the 2026-10-16
  research's recommendation).
- "No re-paste after a stop or deploy" (2026-10-17) against "memory only" (the owner's
  conditional agreement of 2026-09-29).
- "Limits should not be enforced from the code side" (2026-09-23) against ADR-0121 keeping the
  $0.50 per-run cap for user keys.
- "Should not need fly secrets settings" against any design whose master key is a Fly secret.

## The items, in order

Route with `make skill-route ITEM=W28`. Docs only. Item 1 is one pull request. Item 2 may share it or
have its own: the process's stop condition applies, so if a change grows past about twice its
planned size, stop and say so before going on. Each is deployed and checked live.

1. **W28 research: decisions 1, 2 and 4, and the tensions above.** Write
   `docs/analysis/<date>-w28-key-storage-research.md`, covering every point of `w28-research-brief.md`
   and, in particular:
   - how other products keep users' own API keys, and the patterns they use (memory only;
     database with envelope encryption; a key-management service or vault; an encrypted cookie;
     the browser only); for each, what an attacker needs to read a key, including the limit the
     brief found: whoever can deploy code to the app can read a key in any design where the
     server decrypts it, so compare designs by how far they limit the damage (spend limits on the
     key, revocation, an audit trail);
   - Fly's own options, among them the `secretkeys` encrypt and decrypt endpoints of the Machines
     API (whether they are a supported, priced product is UNVERIFIED), and Fly's volume snapshots
     (kept 5 days by default, per the brief, so a deleted key may live on);
   - OpenRouter: its OAuth sign-in (PKCE), its key credit limits and expiry, and its acceptance of
     calls straight from a browser (a browser-only design would move the app's server-side calls);
   - the judge and peer critique on the user's key; the web-search provider's calls (Tavily) under a
     user key; what `/status` and the page's banners show for a run on a user key;
   - the build constraints the inventory found, so the decisions are buildable: every decorated
     function in `src/product_app/` counts toward a cap of 55, and the count is 55 today
     (`tests/unit/test_mutation_test_set_integrity.py`): routes, validators, properties and class
     methods alike, so a new route must use `add_api_route`, and a new validator needs another
     form or a reviewed raise of the cap; tests pin W28 as PENDING, ADR-0121 as
     PROPOSED and the credential-source enum; the session store's schema needs a guarded
     migration; a new setting goes into `.env.example` too; the first build pull request removes
     W28's board needle, so W28 must be re-pinned or it shows DONE while later pull requests remain;
   - the tests the build must pass: the 11 failure-mode tests in the raw map and the 21 in
     `key-safety-tests-2026-10-13.md`, merged into one list.
   Then ask the owner, in one batch (the question tool takes at most four questions per call, so use
   three or four calls back to back for the ten or more questions), each question with a concrete example and a recommendation:
   decisions 1, 2, 4, 5 and 6, the four tensions above, and whether the four transcript-only quotes
   still hold. Record each answer as a CHG row in the owner's words. Then write the ADR that records
   the decided design and supersedes ADR-0121 (do not edit ADR-0121), and regenerate the ADR index.
   Mark it Accepted for the decided parts only: `tests/unit/test_live_posture_check.py` pins the
   exact list of ADRs not in force (0001, 0014, 0060, 0121), so a new Proposed ADR turns it red
   unless that test changes in the same pull request, with a reason. Last, write the prompt for the
   session that builds W28, from `.agents/skills/work-item-delivery/prompt-template.md`, naming
   every decision, input file and constraint it needs.
   No W28 code (CHG-061): W28 is built later, after W85, W86, W100, W87, W88, W80, W75 and W76.
2. **One source of truth for W28 (the owner's request of 2026-10-17, CHG-062).** The new research file
   becomes the one W28 analysis. It carries forward everything still valid from the earlier W28
   documents, says where each point went, and links the CHG rows and the new ADR.
   - Earlier W28 analysis documents get a one-line "Superseded by <new file>" note at the top, or
     move to `docs/archive/2026-10/` (run `ls` there first). Never delete one.
   - `docs/analysis/2026-09-23-byok-failure-modes.md` keeps its path: the frozen W28 board row and
     ADR-0121 link to it. It gets the note only.
   - The June documents that describe a bring-your-own-key feature as built (more than 20, listed
     in `w28-inventory-repo.md` section 3) are corrected or marked, and the requirement conflicts
     (FR-012 "Required" in `docs/10` and "Optional" in `docs/17`; AC-025 and AC-026 meaning
     different things in `docs/12` and `docs/54`; the scope of `docs/01` against `docs/115`; the test
     files `docs/18` names that never existed) are resolved by decision 6, in the same pull request.
   - The plan on `w28/byok-pr1-plan` comes onto `main` as an archived file; every citation of the
     branch or the old path is repointed (`git grep` each); once that pull request is merged and
     deployed, close draft #525 and delete the branch (CHG-047). The local worktree and local
     branch were already removed on 2026-10-17; the raw map's unique findings go into the new file,
     and the raw map itself stays outside the repository.
   - The W28 board row's text is pinned by `tests/unit/test_one_status_review_round_1.py`; leave it,
     and point W28's Parked line at the new file.
   - The public repository rule (CHG-060): write no reproduction steps for a live, unfixed gap.

## Approvals

Sending this prompt approves the following for up to two pull requests (item 1, and item 2 if it
has its own) and the end-of-session handoff (docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""`.
- Deploy.
- Close draft #525 and delete the branch `w28/byok-pr1-plan`, only once CHG-047's conditions hold.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is allowed:
- no paid call;
- no `fly secrets` change;
- no change to GitHub's repository settings;
- no attack on production;
- no W28 code, and no change to an OpenRouter, Fly or Google account (a trial of OpenRouter's
  OAuth sign-in or Fly's key endpoints is the owner's to run: give the owner the exact steps).

## End of session

1. Write the narrative handoff. Every "merged" or "in production" must cite its pull request.
2. Write the next session's prompt from `.agents/skills/work-item-delivery/prompt-template.md`.
3. In the handoff pull request, move this file into `docs/archive/YYYY-MM/` (run `ls` there first;
   add a date suffix if the name exists) and commit the next prompt at the root.
4. Run `make handoff` last. It prints the line for the owner to paste; end the closing status block
   with that line under "Next action".
