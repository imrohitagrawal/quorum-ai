# Session handoff — 2026-09-05

Executed the 2026-09-04 handoff's plan, items 1 and 2. **PR B and PR C are
merged and verified running in production.** Item 0 (the UI-truthfulness work)
is now complete: PR A shipped 2026-09-04, PR B and PR C shipped here.

## What is live

| | SHA | Verified |
|---|---|---|
| ADR-0099 — mechanism copy | `0e91052` | deploy JOB success, `/status.build_sha` matches, live `/ui` HTML checked |
| ADR-0100 — receipt attribution note | `50d4497` | deploy JOB success, `/status.build_sha` matches |

Production at `50d4497`: `live_execution`, `judge_enabled`, `peer_critique_enabled`
all true, `global_daily_spend_usd = 0`. **No money was spent this session.**

Confirmed on the live site after ADR-0099: `"moderator model"`,
`"planned, not yet built"` and `"Per-model debate detail is not captured"` are
ABSENT; the new copy is present.

## The next item is unchanged: Item 1, the clipped-critique defect

The 2026-09-04 plan's steps 3-7 are untouched. Item 1 (`DEBATE_ROUND_MAX_TOKENS
= 2000`, 7 of 8 critique calls clipped) is still live in production and still
costs nothing to start.

## What the next session must NOT re-derive

**The moderator shape is still reachable in production.** `_build_peer_round`
returns `None` — falling back to the moderator — when the flag is off, when NO
slot is eligible, or when a cancel lands before the first dispatch. Round 2 can
also be skipped entirely. `critique_shape` is stamped PER ROUND. Any copy
describing a run must read the run's own shape.

**A critic that returns nothing still yields a `SlotCritique`** with Quorum's
template and `critique_mode` left at `"fallback"`, while the round stays shaped
`"peer"`. So `critique_shape === "peer"` means critics were DISPATCHED, not that
any answered. `describePeerCritique` counts `critique_mode === "live"` for
exactly this reason.

**`#cost-confirmation` is dead markup.** `hidden` in the template, and `app.js`
sets `.hidden = true` and never false. Its "10-30%" cost claim has never been
shown to anyone. Four places in the repo already said so and a session still
spent a round rewriting it. **The LIVE cost copy is `#cost-gate-cap-note`, the
`.cost-gate .lede` and `renderLiveCap`'s `live-cap-note`** — and they are
already careful ("the worst case this run is priced at").

**`max_cost_usd` is NOT an unqualified ceiling.** `costs.py` says in its own
words: *"Do not restore an unqualified 'true ceiling' wording while these
hold."* It bounds OUTPUT only; the `:online` search fee is priced at `0.0` by
accepted decision, measured at 76.7% of the approved figure on one run. Do not
write UI copy promising the bill cannot exceed the cap — review has now refused
that wording twice.

**`debate_round_cost` is `max(peer_round_cost, moderator_round_cost)`**, not an
unconditional sum over four slots. With cheap enough slots the max picks the
moderator and the estimate prices zero critique calls.

## The measured lesson from this session

**Two adversarial review rounds found SEVEN contract-level defects in work that
was already locally green, and most were in the TESTS, not the code.** Recorded
because the pattern repeats:

- a gate silently WEAKENED — moving copy out of an `mkEl(...)` literal put it
  beyond `_extract_mkel_literals`, so `BANNED_EXCHANGE_CLAIMS` stopped covering
  the served sentence;
- the entire user-visible fix REVERTIBLE GREEN — the helper left as dead code
  and both call sites restored, 9 of 9 passing. A mutation proof on a FUNCTION
  proves nothing about whether the render path calls it;
- a fix that REPRODUCED ITS OWN DEFECT with the sign flipped — the caption that
  over-credited the models was corrected into one that erased four real
  critiques;
- a fixture that INVERTED the server's arithmetic, so the spec named "explains
  why the Synthesis row looks like a saving" was green over a receipt showing no
  saving;
- a note asserting "the totals agree" directly above a row reading
  `$0.19 -> $0.202`.

**And roughly a third of the PROSE claims failed verification** — "five test
files" (three), "four false moderator claims" (one), "five AC-019 conjuncts"
(fourteen `&&`), "appears in exactly one place" (two), "#256's largest cause was
the judge" (debate was 60% of the gap, the judge 24.9%). Every one was inherited
or invented and none was checked before writing. Rule 11a is the cheapest
mitigation available and it still needs saying out loud in every reviewer prompt.

**The committed mutation proof earned its keep immediately.** Writing
`scripts/proofs/mechanism_copy_mutations.py` found TWO surviving mutants in
fixes that had already been reported done — both verified by hand in a shell and
never turned into a test. A count nobody can re-run is not evidence.

## Traps paid for again this session

- **`make quality` is `format-check lint type-check test`.** It failed three
  times before reaching the tests, and every time the last cheerful line on
  screen was ruff's `All checks passed!`. Read the exit code from a FILE.
- **`; echo "EXIT=$?"` reports echo's status.** A playwright run reporting
  `8 failed` came back as "exit code 0" through that idiom.
- **`e2e/playwright-report/` breaks `test_code_text_strips_js_comments`.** It is
  gitignored, so the guard finds it by `rglob` and CI never sees it. Reads
  exactly like a diff regression. Delete it by name, twice per session.
- **The visual baselines did NOT need re-seeding**, contrary to a prediction
  made here from a stale darwin baseline. Darwin expects 3137px against a page
  that renders ~3360-3385; that gap says nothing about whether the LINUX
  comparison exceeds its 1% tolerance. Do not infer one from the other.
- **A `git archive HEAD` copy does not contain uncommitted work** — a mutation
  proof run against one silently measured 2 tests instead of 6.

## Open, untouched

`#290`, `#268`, `#105`. The window (`configs/live-execution-windows.json`)
expires `2026-09-08T07:51:25Z` and needs its daily human re-affirmation on #290.
