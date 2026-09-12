# ADR-0111: A lapsed live-execution window is a one-edit revert, not a refusal

## Status

Accepted — 2026-09-12.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture. It changes only the mechanics of TURNING ONE
OFF.

## Context

`scripts/close_live_window.py` (`make close-window`) exists because the obvious
revert of a live-execution posture — flip `OPENROUTER_LIVE_EXECUTION_ENABLED`
back to `"false"` and leave `configs/live-execution-windows.json` alone — is
refused by
`tests/unit/test_live_posture_check.py::test_the_shipped_declaration_file_declares_no_window_right_now`.
A window still covering `now` may not be committed while the flag reads off. The
only valid single-commit form is therefore two edits together. On 2026-08-31
(#407) that deduction was not made under incident pressure and the gate blocked
the revert for ~4.5 hours while production kept serving a spend-capable posture
(that figure is #407's own title; its body's timestamps give 5.2h RED-to-GREEN
and 9.1h to merge, so it is not re-derivable from the issue — quoted as
inherited, not measured).

**The script handled the case where an operator has the most context, and
refused the case where it has the least.** Measured 2026-09-12 by reconstructing
the state on a `git archive` copy — flag `"true"`, newest window `expires_at`
`2026-09-11T07:51:25Z`, i.e. already past:

```
$ python3 scripts/close_live_window.py
EXIT=1
no live-execution window is currently open — nothing to close.
Checked .../configs/live-execution-windows.json: every entry is either 'standing',
not yet started, or already expired. If you intended to revert a live posture, the
flag may already be off, or the window that sanctioned it has already lapsed on its own.

$ grep -n '^\s*OPENROUTER_LIVE_EXECUTION_ENABLED' fly.toml
74:  OPENROUTER_LIVE_EXECUTION_ENABLED = "true"
```

The flag is untouched. The message **names this exact situation** — "the window
that sanctioned it has already lapsed on its own" — and then declines to act on
it.

That is not a hypothetical. It is the 2026-09-11 shape: the window lapsed at
07:51:25Z and production stayed `live_execution: true` for **21.6-25.5 hours
past that expiry**. Compounding
it, the watchdog meant to catch this runs every 2–6 hours in practice against a
declared 30 minutes (filed as #459: 38 scheduled gaps sampled over just under 6
days, zero under 35 minutes, median 3h52.8, max 5h59.4 — that band is the
sample's, not a bound; the wider 18-day history holds one 24-minute gap and one
of 12h51).

**On the exposure figure.** An earlier draft of this ADR, its commit, and issue
#459 all said ~10.8h. That was wrong by roughly 14 hours, and the provenance is
worth recording because it is a three-hop inherited-claim decay: 10.8h was
measured by an earlier session at about 18:40Z on 2026-09-11, written into
commit `522f8c9`'s SUBJECT, landed at 08:41Z on 2026-09-12 without being
re-measured, and was then copied here from that subject. The bracket above is
what the evidence actually supports — the watchdog was still failing at
2026-09-12T05:30:30Z and first succeeded at 09:22:51Z, so production stopped
serving the posture between those two instants. No record pins the exact moment,
which is why this is a range and not a point.

`find_open_windows` is why: `if opened <= now < expires`. A lapsed window is not
"open", so the selection is empty and the script bails.

## Decision

**When no window covers `now` and none is `standing`, a flag still reading
`"true"` is STRANDED — flip it, alone.**

Four states, and two of them are refusals:

| state | action |
|---|---|
| a `time_boxed` window covers `now` | both edits, as before |
| nothing covers `now`, no `standing` entry, flag ON | **flip the flag only**, exit 0 |
| nothing covers `now`, no `standing` entry, flag already off | refuse — nothing to revert |
| a `standing` window is declared | refuse — see below |

**The declaration file is NOT touched in the lapsed case.** Nothing covers `now`,
so there is no `expires_at` to stamp, and rewriting a lapsed entry's expiry would
falsify the record of when the window actually ended. Proven by md5: the file is
byte-identical across the revert.

**One edit is valid here precisely because the gate is already satisfied.** The
two-edit requirement exists to stop a dangling OPEN declaration sitting beside an
off flag. A lapsed declaration is not dangling — no window covers `now` either
way — so `test_the_shipped_declaration_file_declares_no_window_right_now` passes
before and after. This is the narrower case, not the harder one.

**A `standing` window still refuses.** It has no `expires_at` and legitimately
sanctions a live posture for as long as it stands, so a `"true"` flag beside one
is the declared state, not a stranded flag. Ending a standing window is a policy
decision this script does not make for an entry whose `mode` reads `standing`.
The revert is gated on "nothing covers `now` **and** nothing is standing", and
`has_standing_window()` is that predicate.

**An unrecognised `mode` refuses outright (exit 2), and that was a defect found
in review.** The declaration file's README says an unrecognised mode makes the
WHOLE FILE untrusted, and `find_open_windows` already mirrored that. The first
version of this change did NOT: `has_standing_window` matched `mode ==
"standing"` exactly, so a wrongly-cased `"Standing"` was invisible to both
predicates, fell into the lapsed-revert branch, and the flag was flipped —
**silently ending a standing sanction, the one thing this branch must never
do.** Two independent reviewers demonstrated it; reproduced directly:

```
$ python3 scripts/close_live_window.py --fly-toml t/fly.toml --windows-file t/w.json
  (windows: [{"mode": "Standing", ...}], flag "true")
EXIT=0
flag after: "false"      <-- a standing sanction, silently ended
```

`unrecognised_modes()` now refuses first, so nothing is concluded from an
untrusted file. Mutations 01, 03 and 08 are the three ways of losing this, and
all three are killed. A caveat this ADR will not overstate: an unrecognised mode
is a *refusal*, so the stranded-flag case inside an untrusted file still needs a
human — which is correct, because the file cannot be read.

## Rejected alternatives

- **Widen `find_open_windows` to return lapsed entries.** Rejected: it is also
  the predicate that decides what to REWRITE, so a lapsed entry would get its
  `expires_at` stamped to `now` and the record of when the window really ended
  would be destroyed. The bug is in `main`'s response to an empty selection, not
  in the selection.
- **Always flip the flag whenever nothing covers `now`.** Simplest, and wrong:
  it silently ends a `standing` window's sanction, which is a policy decision.
  Mutation 01 is this alternative and it is killed.
- **Leave the script alone and document the manual two-step.** Rejected: the
  script exists *because* a manual deduction under incident pressure failed once
  (#407). Documenting a manual path for the likelier case rebuilds the original
  defect.
- **Have the script also open a tracking issue or alert.** Out of scope; it is a
  local mechanical revert, and the posture watchdog already files issues.

## Consequences

- `make close-window` now resolves the 2026-09-11 incident shape in one command.
  Verified end to end on a reconstructed copy: exit 0, flag flipped, declaration
  file md5-identical, and a second run correctly exits 1 with "nothing to
  revert".
- The two refusals now carry **different** messages, so an operator can tell
  "already reverted" from "a standing window sanctions this". The old single
  message conflated them and was the reason the lapsed case read as expected
  behaviour rather than a defect.
- **The fix LOOSENS a refusal, so both directions are pinned.** The pre-existing
  `test_main_refuses_when_nothing_is_open` (flag already off) is unchanged and is
  the positive partner; new tests cover the standing boundary, a standing window
  beside a lapsed one, an unrecognised mode, and the lapsed revert itself.
- **The success message names what was actually found**, because an earlier
  version asserted "the window has already lapsed" in every branch — false for an
  empty declaration (nothing ever existed) and for a window not yet opened. It
  now reports the real expiry instant, or "has not started yet", or "no window is
  declared at all — check for a fly secrets override".
- **The revert tells the operator to DEPLOY and verify `/status.live_execution`.**
  Editing a tracked file changes nothing in production until it ships, and a
  `fly secrets set` would override `fly.toml`'s `[env]` entirely. The two-edit
  path always said so; the one-edit path shipped without it in the first version,
  which is a false completion signal on the incident path.
- It does not make a stranded flag *detectable* any faster — that is #459, the
  watchdog cadence, and is untouched here.

## How this is proven

`scripts/proofs/close_lapsed_window_mutations.py` — **11 mutations, all KILLED**
against a green 271-test baseline (`test_close_live_window.py` +
`test_live_posture_check.py`), every restore byte-identical with `diff -q` from a
`cp` copy, never `git checkout`, and re-run after `make format`.

01-03 attack the standing boundary (dropping the guard, and forcing
`has_standing_window` to each constant). 04-07 attack the revert itself
(computing the new text but never writing it, reporting failure instead of
success, also rewriting the declaration file, and treating an already-off flag as
a successful revert). **08-11 are the four defects adversarial review found in
the first version**: an unrecognised mode read as "no window" (the dangerous
one), every absence reported as a lapse, the deploy instruction dropped, and the
two refusals collapsed into one generic message.

Two of these are worth recording as process rather than result. Mutations 05/06
reported `ANCHOR NOT UNIQUE (x0)` after the message text changed under them — the
uniqueness guard refusing rather than reporting a false pass. And mutation 11
**survived twice** before it killed: first because nothing read the standing
message at all (a `capsys` fixture was requested and never used), then because
asserting `"standing" in err` still matched a mutated message that kept the word
later in the same string. It only bites now that the test asserts the clause
unique to that branch and asserts the other refusal's text is absent.
