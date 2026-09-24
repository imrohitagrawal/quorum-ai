# ADR-0122: Peer critique cannot outlive a live window

## Status

Accepted — 2026-09-24. **Product-owner decision, given in chat on 2026-09-24**
(CHG-012 records it; `docs/analysis/2026-09-22-decision-register.md`, section
2026-09-24, D2, has the transcript record). The owner's own words, answering
the session's recommendation to couple `PEER_CRITIQUE_ENABLED` to the window
scripts and flip it to `"false"` now: *"#458: yes, couple the flag"*
(transcript `df5e9b18`, `type: user`, `2026-09-24T06:20:42Z`). Everything in
this record beyond that sentence — which script writes the flag, what the
pre-merge gate refuses, what the watchdog reports, and that escalating the
watchdog's report to an alert is left for the owner — is the session's
design under that decision, and is marked so where it matters.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture. It changes what CLOSING a window does and
what a committed `fly.toml` may carry. It flips one flag, `PEER_CRITIQUE_ENABLED`,
from `"true"` to `"false"`, by running the mechanism it adds — the one flag
change the owner authorised for this session, and the only one it makes.

Amends ADR-0097 §3 ("It never alerts on its own") in wording only: the
flag-off report line now names a true peer flag as DRIFT and still does not
alert. Amends ADR-0111's state table: the lapsed revert flips two flags, and
"flag already off" now means both. Amends ADR-0116's Consequences ("no gate
couples the flags") and answers its rejected alternative "couple the two
flags so the window script flips both", which that record left to the
product owner and the owner has now decided.

## Context

Peer critique (#290, ADR-0093) replaces the two moderator debate calls with
up to eight critic calls at four models' prices. It is gated at dispatch on
live execution AND a key (`debate._build_peer_round`; ADR-0116's three-term
predicate), so with live execution off it costs nothing. It was switched on
in production by the same commit that opened the 2026-09-03 live window and
was left on when that window's flag was reverted (#457, 2026-09-12): from
then until this change production's `fly.toml` read
`PEER_CRITIQUE_ENABLED = "true"` beside `OPENROUTER_LIVE_EXECUTION_ENABLED =
"false"`, and `/status` reported `peer_critique_enabled: true,
peer_critique_in_effect: false` (read on 2026-09-24 at build `42cd965`).

Issue #458 named the trap: re-opening a window would have turned peer
critique back on with it, unread, at up to eight critic calls per run. Three
facts made it a trap rather than a setting:

- `fly.toml`'s own comment said the flag "flips back with
  OPENROUTER_LIVE_EXECUTION_ENABLED"; it did not, and the file corrected
  itself to say so (`grep -n PEER_CRITIQUE scripts/close_live_window.py`
  exited 1, verified 2026-09-11, and again on 2026-09-24 before this change).
- No test anywhere read `PEER_CRITIQUE_ENABLED` out of `fly.toml`
  (`grep -rn PEER_CRITIQUE_ENABLED tests/ scripts/ .github/` → comment-only
  hits, zero assertions — the issue's own measurement, re-run on 2026-09-24
  with the same result). So flipping the value would have turned nothing red,
  and the value could drift back just as silently.
- The estimator prices critic calls from the raw flag, not from "in effect"
  (`costs.py`, the three reads of `settings.peer_critique_enabled`; noted by
  PR #491's reviewer). So production's pre-run estimate priced eight critic
  calls that no run made, for the whole flag-true/live-off interval.

ADR-0116 (2026-09-21) made the copy tell the truth about that state and
explicitly did not couple the flags: "it changes what a live window does,
which is the product owner's decision, not a copy fix". That decision has now
been taken.

## Decision

**1. Closing a window turns peer critique off.** `scripts/close_live_window.py`
(`make close-window`) sets `PEER_CRITIQUE_ENABLED = "false"` in `fly.toml` on
the same pass that sets the live flag, on BOTH of its revert paths: the
covering-window path (two edits, ADR-0111 "as before") and the lapsed path
(#460). The two key edits land on one text and one write, so the write-order
contract of #407 is unchanged and `test_main_writes_the_flag_before_the_window_declaration`
still pins it. The script's messages name each flag it moved.

**2. A stranded peer flag is a one-edit revert, like a stranded live flag.**
ADR-0111's state "nothing covers `now`, no standing entry, flag ON → flip the
flag only" now reads either flag: live already off and peer still on is
exactly the state production shipped from 2026-09-12 to 2026-09-24, and the
script reverts it (exit 0) instead of answering "nothing to close" (exit 1).
"Flag already off → refuse" now means BOTH already off. Every refusal
(standing window, untrusted declaration, unrecognised mode) leaves both flags
untouched, pinned in `tests/unit/test_close_live_window.py`.

**3. An absent peer key is a refusal, not a skip.** `set_flag_false` applies
the live flag's own rules to the peer key: absent or duplicated, it raises and
the script exits 2 without writing. A silent skip would report a closed window
while peer critique stayed exactly as armed as it was — the failure class the
live flag's refusal already names.

**4. The committed `fly.toml` may not carry the peer flag on while the live
flag is off.** `scripts/live_posture_check.py::refuse_peer_without_live` is the
pre-merge half, used by `tests/unit/test_live_execution_posture_declaration.py`
in the blocking `pytest (Python 3.12)` lane beside `refuse_undeclared_flag`.
Every on-spelling and any typo of the peer value is refused beside an
off-spelling of the live value; a peer flag on beside a live flag on is
allowed, and the existing gate then requires the window that sanctions the
live flag. This is the ON-side coupling: there is no script that opens a
window (opening is a hand edit of `fly.toml` plus a declaration entry in the
same pull request; DEPLOY.md §4), so the coupling on open is a gate, not a
writer.

**5. The watchdog names the served state as drift, and still does not
alert.** `_peer_critique_note`'s flag-true/live-off line now says the flag is
coupled, that a true value there is DRIFT from the committed posture (a Fly
secret, or a deploy that predates the coupling), and that `make close-window`
reverts it. It stays REPORTED (ADR-0097 §3): the package text the session
wrote from the owner's decision says "a drift to report", and the owner's own
words are only "couple the flag". **Escalating this line to an alerting
`PostureDecision` is PROPOSED — AWAITING OWNER**, recorded here and not built:
it would catch a stray `fly secrets set PEER_CRITIQUE_ENABLED` (which no
tracked file and no pre-merge gate can see), at the cost of one correct,
self-closing alert if a watchdog cycle lands between a coupling merge and its
deploy, and it reverses ADR-0097 §3 for one state. Nothing spends in that
state either way: every critic call is gated on live execution.

**6. The population of files that name the flag is pinned.**
`test_no_file_outside_the_window_mechanism_names_the_peer_flag` asserts set
equality over every tracked file under `scripts/`, `src/`, `.github/`,
`configs/` and the `Makefile` that contains the literal `PEER_CRITIQUE_ENABLED`
plus the `Dockerfile`, `docker-compose.yml`, `.env.example`, `DEPLOY.md` and
every tracked `*.sh` at any depth, matched case-insensitively on a word
boundary because the app's settings are case-insensitive (six files today: the closer, the checker, one proof script
that sets the environment variable for a local sweep, the watchdog workflow
whose alert body names the key, the local `.env.example`, and DEPLOY.md which
names the Fly-secret route). "No other writer exists" is thereby a check
rather than a sentence (AGENTS rule 1a); a new mention is triaged, not
tolerated. What it cannot see, stated in the test: a Fly secret; a hand edit
of `fly.toml` (which decision 4 refuses when it strands the flag, and whose
flag lines a second gate keeps in the one `KEY = "value"` shape the closer
can edit); and `docs/`, `e2e/`, `tests/`, which are outside the scan except
for any `*.sh` they hold.

**7. The production value flips to `"false"`, by running the mechanism.** The
diff to `fly.toml` in this change is the output of
`python3 scripts/close_live_window.py` run on the tree (lapsed path, live
already off, peer on): it flipped the one line and printed that it did so.
That is the demonstration of decision 2 on the real file.

## Measurements

All on the `wp/458-peer-flag-window` worktree at `42cd965` plus this change,
locally, no paid call.

| what | command | result |
|---|---|---|
| RED before the code | `uv run pytest tests/unit/test_live_execution_posture_declaration.py tests/unit/test_close_live_window.py tests/unit/test_posture_reports_peer_critique.py -q --no-cov`, this change's three test files over `origin/main`'s closer, checker and `fly.toml` | `52 failed, 71 passed` — 13 distinct tests, 12 of them new (the real-file gate red on the shipped `fly.toml`, the closer's peer tests, the case-collision and line-shape gates) and one pre-existing flag-off wording test extended with the DRIFT assertions. The first commit's test set, before the two review rounds added three tests, gave `50 failed, 70 passed` |
| GREEN after | same, plus `tests/unit/test_live_posture_check.py tests/unit/test_ui_honesty.py tests/unit/test_w4_copy_outside_run_path.py tests/integration/test_peer_critique_is_observable.py` | `396 passed` |
| the closer on the real tree | `python3 scripts/close_live_window.py` | exit 0; `PEER_CRITIQUE_ENABLED was still on with NO window sanctioning it. The window that authorised it expired at 2026-09-11T07:51:25Z, on its own. Flipped PEER_CRITIQUE_ENABLED to "false"`; `git diff --stat fly.toml` → 1 line; `configs/` untouched |
| mutation proof, closer | `uv run python scripts/proofs/close_lapsed_window_mutations.py` | `15 killed / 15` against a green 284-test baseline (12 inherited from ADR-0111 — that record says "11", but its list held 12 entries, two labelled "09"; three re-anchored, 05, 07 and 10, because the closer's condition and message text changed — and 3 new: the peer flip dropped from the lapsed path, dropped from the covering path, the peer key alone skipped when absent instead of refused) |
| mutation proof, watchdog note | `uv run python scripts/proofs/peer_critique_visibility_mutations.py` | `19 killed / 19` against a green 267-test baseline, unchanged in count; anchors intact after the wording change |
| the served estimate, default panel, search on | `PEER_CRITIQUE_ENABLED=<v> QUORUM_TOKEN_SECRET=x PYTHONPATH=src uv run python -c '…'` building `ModelSlot(slot_number=i+1, model_id=m, search=True)` over `DEFAULT_MODEL_IDS` and calling `cost_estimation_service.estimate(query_text="What is the capital of France and why?", model_slots=slots, account_id="acct-measure")` (the fourth decimal moves with the query text; the differences do not) | flag true: point `0.1271`, bound `0.2072`; flag false: point `0.1073`, bound `0.1684`; band `allow` both. Judge `openai/gpt-5-mini` from the local `.env`; the judge row is the same on both sides, so the DIFFERENCE (point −0.0198, bound −0.0388) is the two debate rows going from four critic calls each to one moderator call each, and does not depend on the judge |

The estimate change is a consequence of the flip, not a moved constant: no
default, cap, band or ceiling in `costs.py` changes. Production's estimate
stops pricing critic calls that no run makes while live execution is off.

## Consequences

- **Re-opening a window is now a two-flag edit if peer critique is wanted
  inside it**: set both `OPENROUTER_LIVE_EXECUTION_ENABLED` and
  `PEER_CRITIQUE_ENABLED` to `"true"` with the covering declaration entry in
  the same pull request (decision 4 allows peer on only beside live on; the
  existing gate then requires the window). A window opened for live execution
  alone runs the moderator shape, which is what every run has taken since
  2026-09-12. DEPLOY.md §4 says so.
- **`make close-window` closes both**, and its prose, `fly.toml`'s comment,
  the watchdog's alert body and the Makefile header now say so instead of the
  opposite (`fly.toml` carried a dated grep proving the closer never named the
  flag; it now carries the opposite dated grep).
- **Production's served estimate for the default panel drops by the two
  debate rows** (Measurements). ADR-0110, ADR-0113, ADR-0114 and ADR-0115
  report envelope figures measured with peer critique and the judge on
  (0110 and 0113 say so in a header sentence, 0115 in its posture line, 0114
  by the judge posture it prices); those were true measurements of the
  posture on their dates and are amended by a dated Status line, not
  rewritten. The FAQ's "eighteen in
  production" and its default-panel dollar figure are corrected to the two
  shapes without a new number.
- **`/status.peer_critique_enabled` reads `false` in production after this
  deploys**, and the watchdog's every-cycle line says
  `peer_critique_enabled=false`. If it reads `true` after the deploy, a Fly
  secret overrides `fly.toml` — that is the drift decision 5 names, and the
  check is `curl -s https://quorum.stackclimb.com/status | jq .peer_critique_enabled`.
- **Between merge and deploy, nothing alerts** (decision 5 keeps the report
  non-alerting). Had the alert been built, one correct alert could have opened
  in that gap.
- **The closer's committed mutation harness grew from 12 to 15 entries**
  (ADR-0111 says "11 mutations … 271-test baseline"; the list it describes
  held 12, two of them labelled "09" — the figure stays as that record's
  dated text, corrected in its amendment), the watchdog's harness re-run
  unchanged at 19.

## Rejected alternatives

- **Flip the value and leave the coupling to prose.** The issue's own
  measurement: nothing read the value, so nothing would have stopped it
  drifting back. A corrected sentence lasts until the next change; a gate
  lasts (AGENTS rule 1a).
- **Couple in the estimator instead** (price critics from "in effect", not
  the flag). Fixes the estimate and not the trap: the flag would still come
  back on with the next window. It is also a change to the money bound with
  its own review rounds (`test_peer_bound_is_a_true_ceiling.py` pins the
  peer-on bound from the raw flag), and the owner's decision was the window
  coupling. Recorded as a possible later change, not taken.
- **A `peer` field in the window declaration, beside `judge`.** ADR-0097
  rejected a per-window declaration for peer critique because its spend is
  inside the run charge and the live window already binds the money; that
  reasoning still holds, and a defaulted money field would be a decision
  nobody made. The coupling makes the flag follow the window without a second
  declaration to keep in step.
- **Alert on the drift now.** Decision 5: proposed, not built, because the
  package text says "report", the owner's words say "couple", and ADR-0097 §3
  says "never alerts on its own" — three records the session should not
  override on its own reading.
- **Tolerate an absent peer key in `fly.toml`.** Decision 3: a skip that
  reports success is the live flag's own named failure class.

## Related

- #458 (this), #457 (the flip this issue deferred), #290 / ADR-0093 (peer
  critique), ADR-0097 (reported, not declared), ADR-0111 (the lapsed revert),
  ADR-0116 (copy follows "in effect"), ADR-0070 / ADR-0071 (the window
  mechanism and the watchdog), CHG-012.
