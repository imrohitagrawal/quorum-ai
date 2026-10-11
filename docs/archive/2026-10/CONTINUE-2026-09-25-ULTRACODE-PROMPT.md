> **Archived 2026-10-11** (CHG-040 (c)). The process now lives in `.agents/skills/work-item-delivery/SKILL.md`; this file is history and is not to be run. Edits: home-directory paths replaced with `~`, and the user name in a transcript folder replaced with `<this repo's project folder>`.

# ULTRACODE — the 2026-09-25 queue: session limits, the invite link, #447 wiring, W7 2 and 3, BYOK draft

ultracode. Workflows and subagents for READ-ONLY fan-out only (understanding,
review, verification). Never for building: subagents share one working tree.

This file was drafted by the 2026-09-25 session at the owner's request; the
owner sending it is the grant in §2 and §3. Where a sentence is quoted with a
time it is the owner's own (`type: user` record in transcript `efe4f2fc`);
everything else is the drafting session's wording.

Work the queue in §5 in order. Every decision you need is in §4; do not
re-ask any of them. Stop only at a §2 hard stop, and write it in the report.

---

## 0. Read first, in this order, then run the checks

1. `AGENTS.md` — it overrides everything here on every technical rule, with
   ONE exception: §2 and §3 of this file are the explicit human approval that
   AGENTS rule 17b requires (push, open a PR, merge, deploy), bounded by §2.
2. `docs/00-factory-console.md`, `docs/session-handoff.md`.
3. `docs/analysis/2026-09-25-session-handoff.md` — what shipped (#499 and
   #502 to #511; #500 closed unmerged, #501 an open draft), what is owed, the
   traps measured, and the Google sign-in runbook (§6).
4. `docs/19-change-control-log.md` rows CHG-012, CHG-021 and CHG-022; board
   rows W7, W29, W30, W31, W32 and W28 in `docs/65-open-work.md`;
   ADR-0122, ADR-0124, ADR-0130, ADR-0131, ADR-0121;
   `docs/analysis/2026-09-25-w7-google-sign-in-failure-modes.md`.

```bash
cd ~/Projects/quorum-ai
git status --porcelain     # expect only CONTINUE-*.md prompts (untracked)
git worktree list          # expect quorum-ai (main) + quorum-ai-wt-268 (parked)
git log --oneline -1       # expect the 2026-09-25 handoff merge or later
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled,sign_in_enabled}'
ls -lt ~/.claude/projects/<this repo's project folder>/*.jsonl | head -3
```

`live_execution` must be false. A transcript written in the last few minutes
means another session may be live: read its tail before taking work. Do NOT
run `make handoff` here; it belongs at §8 only. The
other root `CONTINUE-*` prompts are superseded by this file. Run the
commands, not the numbers: if a figure here disagrees with a command, the
command wins and you say so.

---

## 1. What this session is for

The seven items in §5, in that order, one pull request each (W7's two are two
pull requests), each merged and verified in production before the next
starts. If an item is bigger than it looks, say so, park it (§5) and continue.

---

## 2. HARD STOPS — stop, write it in the report, do not ask twice

- Any paid API call or live run. `/status`, `/ready`, `/metrics`, `/ui/ops`,
  `/estimate` and the free OpenRouter catalog are fine; one free `curl` to an
  upstream for a header or error shape (AGENTS 8c) is fine.
- Opening, extending or re-affirming a live-execution window; editing
  `configs/live-execution-windows.json`; ANY `fly secrets` command. Where a
  change needs a secret (the allow-list, the invite-link signing key), write
  the exact command for the owner and stop there.
- Merging a change to a shipped money VALUE (defaults, caps, bands, ceilings,
  rate limits, mint caps). **Authorised by CHG-022:** W30, W31 and W32 change
  WHO the per-network session limits count and WHO is exempt; they may merge
  provided no cap value moves (the daily cap stays 2, `DAILY_CAP_USD` and
  `GLOBAL_DAILY_CEILING_USD` untouched). If one must move a value: DRAFT, stop.
- Any merge whose `EXPECT_CLOSE` is non-empty. Write `Refs #N` / `Refs W30`,
  never Fixes/Closes/Resolves, in PR title, body and merge body.
- Lowering a threshold, `# pragma: no cover`, deleting or exempting a test.
- Force-push, history rewrite, `git clean`, `git stash`, touching secrets,
  `git add -A` (stage named paths only).
- Recording a decision the owner has not made. §4 is what they decided;
  anything beyond it is `PROPOSED — AWAITING OWNER` in every artefact.
- Writing "half" in price copy, or a range in the landing headline.
- Two fix rounds in a row that add a defect: stop, root-cause, re-plan, report.
- W7: storing a provider key, a password, or any Google token beyond the
  sign-in exchange; storing more than the summary row per run.
- W31/W32: exempting anything from a SPEND limit; an allow-list entry
  without a name and an end date; a range wider than /24 (IPv4) or /48 (IPv6).

---

## 3. Standing authority to merge, when ALL hold and the output of each is shown

1. Required contexts re-derived (`gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`) and each SUCCESS on the PR head SHA.
2. `make quality` and `make validate` exit 0 in the worktree, read as two steps (never through a pipe).
3. `make diff-cover DIFF_BASE=origin/main` green on a COMMITTED, STILL tree, run last after a fresh `make quality`. Nothing edits the tree while any gate runs.
4. `make api-contract`, `make openapi-check`, `make security-scan` exit 0; the e2e lanes per §7 if UI, specs or fixtures changed; `node e2e/tools/check-negative-assertions.mjs <spec>` on every changed spec.
5. Review complete: correctness, break-it and prose lenses (rule 11a verbatim in every prompt), every finding reproduced BY YOU and triaged, zero open CRITICAL_BLOCKER or REQUIRED_CONTRACT. Two rounds max. Each reviewer gets its OWN `git archive HEAD` copy in a `$RANDOM-$RANDOM` directory, a port above 18200, and deletes its copy when done.
6. Every behavioural change has a test proven by mutation (cp aside, check the anchor is unique, mutate, clear `__pycache__`, run, restore from the copy, `cmp`), recorded in the commit body with the verbatim red output. UI changes: the byte-identical proof of the result and transcript views on `goldenCompletedResp()` (AGENTS rule 13e) or, where a view changes by design, the full-document diff with every hunk explained.
7. `make close-guard` with an explicit empty `EXPECT_CLOSE`.
8. Finish the PR body BEFORE the final push (`ci.yml` fires on `edited`).
9. The advisory CI mutation job: read its log for `mutants scored:`; a red one with `0 killed, 0 survived` measured nothing.
10. After merge: every Deploy RUN for the merge SHA enumerated, each Deploy JOB read, exactly one `success`; `/status.build_sha` equals the merge SHA; `/ready` 200.
11. Then `git merge --ff-only origin/main` in the main checkout, delete the branch local and remote, remove the worktree.

---

## 4. The decisions — the owner's, in chat

- **CHG-012 (2026-09-24)** — read it whole. D7 (W7 history rules) and D8
  (BYOK last) govern items 5 to 7 below.
- **CHG-021 (2026-09-25, 08:46:23Z and 08:56:57Z)** — W7's second and third
  pull requests. Owner: *"i agree with your suggestion of "do carry them over,
  but only the runs from the same browser session, at the moment of sign-in,
  capped by the same keep-the-last-5 rule". I agree with Idle expiry for
  signed-in sessions post a reminder where User can decide to keep it active
  or not. I agree with "Sign out everywhere.", "Record sign-in events",
  "Rate-limit the sign-in start". A reminder and re-confirmation from User
  before permanently deleting the account."*
- **Not decided — do not build:** the per-account spend-limit lookup and the
  allowed-emails setting (offers the owner has not answered; handoff §3), and
  paid tiers. The peer drift alert and the visual-flake tolerance are also
  the owner's.
- **CHG-022 (2026-09-25, 13:41:59Z to 13:48:26Z)** — the session limits.
  Owner: *"should we also have an allow list, which would help us allow
  certain IPs for testing purposes? ... if I need to give this application to
  a firm for testing ... multiple people's HRs and hiring managers need to
  test it ... I can simply update their IPs in the allow list, and they will
  be relieved from this check."*; *"I have said yes, so it should not be
  mentioned as awaiting owner. Everything is approved here."*; *"Invite link
  should not be later. I expect it should be planned and included."*
  What was approved is the session's proposal, recorded in CHG-022 items
  (1) to (4). Keep item (3) in the owner's view in every artefact: an
  address list helps only people on the firm's own network; the invite link
  is for everyone else.

---

## 5. The queue

**Parking protocol.** An item that needs a decision not in §4, or is bigger
than one package: push the branch, open a DRAFT PR with the evidence, leave
the worktree, record it in §8's Pending, cut the next worktree fresh off
`origin/main`. Do not idle.

**The order is partly the drafting session's.** The only order the owner
approved on 2026-09-25 is the address fix, the allow-list, then W7's second
pull request (CHG-022). The owner brought the invite link into the plan
without placing it (*"should not be later"*), so it goes right after the
allow-list. W29's place is the session's: CHG-012 D6 records the 2026-09-24
sequence that put #447 before W7 as the session's, uncontested, not the
owner's words; so W29 comes after W7 here, not before it. **The owner
confirmed this order at the close of 2026-09-25 (16:02:06Z, `type: user`):
*"The order looks good."*** Follow the list below as the owner's order; each
PR's rule-20 line cites that confirmation.

**Every item:** dedicated worktree off fresh `origin/main`
(`uv sync --all-extras`; `cd e2e && npm ci` for e2e); failure modes first for
anything touching money, auth or safety (rule 16e); TDD with the verbatim red
output; a mutation proof per behavioural change; ADR and/or CHG row in the
same PR (rule 16d); a board needle that the fix must ADD (never flip a
needle's polarity; if the design names differ from the needle, move the
needle in the same PR and say so); the prose audit; `Refs`.

1. **W30 — count the visitor, not the app.** MEASURE FIRST: what Fly's proxy
   forwards (`Fly-Client-IP`, the `X-Forwarded-For` order) — for example a
   one-line temporary log of the header NAMES and address count, deployed,
   read, removed; never log a full address list longer than it takes to
   measure. Then read the visitor's address only from a trusted proxy peer
   (the Dockerfile's ranges); a forged header from the internet must still be
   ignored (`tests/security/test_trusted_proxy_ips.py`). Both per-network
   limits (daily cap and per-minute) key on it. Model the owner's case in a
   test: two different visitors behind Fly each get their own allowance.
   After the deploy, ask the owner to retest #511 (sign-out and a query after
   sign-in) — the first thing they are waiting for. Ask once, then continue
   with W31; do not wait for the answer.
2. **W31 — the allow-list** (CHG-022 item 2): single addresses or ranges,
   each with a name and an end date; refused at startup if wider than /24 or
   /48; lifts only the two per-network session limits; one secret whose
   exact `fly secrets` command you give the owner; startup log of counts and
   end dates without addresses; exempted requests counted on `/ui/ops`.
3. **W32 — the invite link** (CHG-022 item 4). Failure-mode page first: a
   leaked link, revocation, expiry, whether uses are capped, who can mint
   one (operator only), that it never lifts a spend limit, that the link's
   secret never reaches a log or `Referer`. Propose the design choices the
   owner did not make as `PROPOSED` in the ADR, build the safe default.
4. **W7, 2 of 3 — history and deletion** (CHG-012 D7 + CHG-021 a and f).
   Failure modes first, including two races promised to the owner
   (2026-09-25, 11:30:42Z), each with a test: deleting an account while it is
   signed in on another device; carrying runs over while one is still running.
5. **W7, 3 of 3 — session safety** (CHG-021 b to e; the idle length and the
   rate-limit value are your proposals, as settings, marked as such). The
   third promised race gets a test: "sign out everywhere" while other
   requests of that account are in flight.
6. **W29 — #447, 2 of 2: the judge wiring** (ADR-0124). If the input reserve
   moves a shipped money value: DRAFT and stop.
7. **BYOK** (W28) — first PR as a DRAFT only; ADR-0121 stays
   `PROPOSED — AWAITING OWNER`.

---

## 6. Practices that are not optional

- One concern per PR, merged and deployed before the next starts.
- Verify by executing, including WHERE a thing is (rule 1); UNVERIFIED said
  out loud otherwise.
- Fan out for review, never for building; reviewers told IN CAPITALS not to
  write, edit, `git checkout`, `git stash` or `sed -i`; own copies; own ports.
- Never move the tree under a running reader or gate (rule 9a) — broken
  again on 2026-09-25 and cost a full re-run.
- A GET must survive being fetched twice by something that runs no page code
  (ADR-0131); a test of a browser flow models the repeat fetch.
- Every background wait loop has a wall-clock limit and stops on a result it
  does not recognise (2026-09-25: 8 stale polling shells, up to 1 day 1 hour
  old, found only because the owner asked).
- When a live report arrives, save `fly logs -a quorum-ai --no-tail` to a
  file at once: the buffer is about 100 lines and rolls over within minutes.
- Attribution: "the owner decided X" only with a `type: user` record and its
  time; everything else is the session's wording.
- Keep the board true; regenerate with `make open-work-write`; ADR index with
  `python3 scripts/generate_adr_index.py`; never hand-edit either.
- Plain English to the owner; lead with the answer; the closing block in §8.

---

## 7. Commands that bite

- Fresh worktree: `uv sync --all-extras` before any `uv run`; a bare
  `uv run` builds a venv with no pytest.
- Never `git checkout <file>` to undo a mutation; restore from your `cp`.
- `docs/00-factory-console.md` is regenerated by `make next`; never edit it
  by hand.
- e2e exactly as CI:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  rm -f .data/feedback_events.sqlite3
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <specs> --project=chromium --workers=1 --retries=0
  ```
  Which specs: every `npx playwright test` step in `.github/workflows/e2e.yml`
  names its lane's specs; run each lane the change can reach; for any
  `/ui/ops` change such as W31's counter, that includes the whole second
  lane (axe-all-views, parity-behavior, docs-under-csp, real-integration-smoke,
  degraded-banner, ops-dashboard, ops-navigation). The visual lane fails on this Mac by design; never
  `--update-snapshots`.
- `e2e/tests/review/` is gitignored scratch; delete your own before
  `make quality`.
- `make <target> > /tmp/gate.log 2>&1; echo "EXIT=$?"` — never through a pipe.
- `timeout` does not exist on this box.
- Commit before trusting `make diff-cover`.
- Any new module-level constant in risk-tier code must be triaged in
  `tests/unit/test_risk_constant_pins.py` (bucket A/B/C) or
  `test_every_risk_constant_is_triaged` fails.
- Patch `product_app.config.settings`, not `<module>.settings` (mypy).
- Route counts: `tests/unit/test_mutation_test_set_integrity.py` asserts
  `30 <= len(decorated) <= 55` decorated route functions; add new routes
  with `add_api_route`, as `google_signin.py` does.
- A merge SHA collects several Deploy runs, and the count grows while that
  SHA is main's tip; exactly one Deploy JOB is `success`. Read the jobs,
  never the count.
- From this machine `/v1/session` answered 429 at 12:00Z on 2026-09-25.
  Until W30 ships, that allowance (2 per rolling 24 hours) is shared with
  every visitor, so do not mint sessions from here; production browser
  checks need the owner.
- The cited-paths gate resolves any `tests/…py` token on an added line, even
  in a sentence saying the file does not exist; name a missing file without
  its path.
- `getModelIds()` throws before `/v1/models/defaults` answers; nothing on the
  landing may call it. `test_peer_caption_counts.py` pins the
  `describePeerCritique(` call-site count.
- A dict-literal continuation line measures nothing in diff-cover; the pinned
  literal test is the cover.
- The advisory CI mutation job is never a required check; post its
  `mutants scored:` line on the PR.
- Workflow tool: pass `script` for a new round, never `scriptPath` with it.

---

## 8. Reporting — at the end, and at any hard stop

Closing block, plain English: `Done` (what merged, SHA, running in
production, each with its proving command) / `Verified myself` (what YOU ran,
with output; subagent reports separately) / `Cleanup` (what was deleted, with
command output) / `Pending` (anything parked, with its draft PR and the
decision owed, in the owner's words) / `Next action`.

Before it: `make next`, `make skill-route`, `make handoff`, and a narrative
`docs/analysis/<YYYY-MM-DD>-session-handoff.md` (`-2` for a second session the
same day), merged as its own docs-only PR, deploy verified. If nothing is
outstanding, end with "nothing pending — safe to close this session".
