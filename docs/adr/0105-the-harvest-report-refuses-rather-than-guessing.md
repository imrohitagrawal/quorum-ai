# ADR-0105: The harvest report refuses rather than guessing

## Status

Accepted — 2026-09-07.

Reads the fields ADR-0104 captures. Ships after them, deliberately — see
ADR-0104 §6 for why the capture goes first and alone.

## Context

`scripts/window_measurement_report.py` turns the durable token stream into the
three readings the live-execution window was declared for. It will be run ONCE,
against a ~$0.10 production run, and whatever it prints decides two things that
cost money: whether `DEBATE_ROUND_MAX_TOKENS = 4000` stays, and whether #447 is
closed by reading annotation content (cheap) or by building a credential-guarded
URL fetcher (expensive).

It computes no policy and moves no constant. It is decision SUPPORT, modelled on
`scripts/telemetry_classification_report.py`.

## Decision

**Refuse rather than answer, wherever the data cannot support an answer.** Every
reading here is a negative check — "no row said `length`", "no annotation
carried content" — and all of those are trivially true over nothing. The
precedent script exits 0 over zero rows; this one does not.

Adversarial review then demonstrated **nine further ways it printed a confident
wrong verdict**. Each is now a refusal or a qualification, and each has a test
and a mutant:

| Input | Printed | Now |
|---|---|---|
| every reply at cap, `finish_reason: absent` | `FITS` | `NOT MEASURED` |
| rows with no `query_run_id` | pooled into a "run" | a census, never a run |
| a trailing uncorrelated judge row | took the headline | headline is the NAMED run |
| **two runs, none named** | headlined the newest | **refuses; exit 1** |
| one field-less row beside three rich ones | `BUILD TOO OLD` | answers, with a caveat |
| content key present, all empty | `ROUTE A POSSIBLE` | `ROUTE A UNPROVEN` |
| a 1-character content field | `ROUTE A POSSIBLE` | `ROUTE A THIN` |
| 200 torn lines + 1 good row | a full verdict at exit 0 | refused over a 5% ceiling |
| a reply longer than the cap | `AT THE CEILING` | `OVER THE CAP` |

### The headline refusal is the important one

Measured end to end: with a paid measurement run and one ordinary query from a
second user overlapping it, the headline landed on the ordinary query and
printed the **exact opposite** of the paid run in both money directions —
`FITS` beside the paid run's `CLIPPED 4 of 4`, and `NO ANNOTATIONS` beside its
`ROUTE A POSSIBLE, 5600 characters`. A reader acting on it keeps a cap that does
not fit AND builds a fetcher the data says is unnecessary.

One concurrent query on a live `/ui` is enough. So with more than one correlated
run and none named, the report prints every run, chooses no headline, says so on
stderr and exits non-zero. `--run <id>` names it; each run prints its timestamp
window so a reader can choose. **There is no honest way to guess which run the
money was spent on.**

### One cap governs BOTH debate rounds

`debate.py` dispatches round 1 and round 2 through one seam with one
`max_tokens=DEBATE_ROUND_MAX_TOKENS`. An earlier version filtered
`stage == "debate_round_2"` and so inspected four of the eight calls that
constant governs — while ADR-0102's own table records the previous run's
**round 1 slot 4 stopping at 2000/length**. On a run where round 1 clips and
round 2 does not it printed `FITS`, and there was no verdict it could print for
that outcome. It reads both and splits them: ADR-0096 made round 2 carry the
revised answer `synthesis` reads, so a round-2 clip is the more expensive one and
the verdict line names which round.

### Readings are per call where the evidence is per call

The "our reader missed them" reading was gated on the whole run's annotation
total, so one annotation reaching `delta` anywhere disabled it — including for
calls whose content sat where the fold never looks. It is per call now, and a
call read at `delta` that ALSO had annotations elsewhere gets a
`PARTIAL SAMPLE` line rather than being written off: `annotation_sites` is a
SET joined with commas, so `"delta,message"` means the delta half WAS collected.

## Consequences

- **The harvest procedure changes.** `--run` is required whenever the file holds
  more than one run, which the production volume normally does.
  `CONTINUE-HARVEST-AND-LIVE-RUN-ULTRACODE-PROMPT.md` is updated in this change:
  following it verbatim would otherwise exit 1.
- Known limitation, printed on every report: the sink rotates at 4 MiB with 4
  backups and this reads only the active file, so a run straddling a rotation is
  reported from its tail.
- The report prints TOKENS and no dollar figure. The run's own receipt prices
  them, and two numbers for one fact is how they come to disagree.
- **A reader defect is free to fix.** The telemetry is durable, so a wrong
  reading is corrected by editing this script and re-reading the same file. That
  asymmetry is why this ships second and why its bar is lower than the capture's.

## How this was verified

- The mutation proof gains the reader's mutants; run it with
  `python scripts/prove_annotation_capture_bites.py`.
- Every row of the table above was reproduced by building the fixture, running
  the real script, and reading its verbatim output — before and after.
- **Four defects were found in tests that looked right**, three of them by the
  committed proof rather than by reading: an interleaving fixture whose two
  orderings gave the same answer; a content-rank fixture whose answer was the
  same under the documented order and its permutation; a `--run` test naming the
  one run a "use the default" mutant also picks; and argv tests asserting only
  exit code 2, so each specific refusal was satisfied by a different guard.
- **Do not read a kill rate as adequacy.** A reviewer wrote seven mutants this
  set did not contain and two survived, both judgement VALUES rather than control
  flow. ADR-0104 names the three classes the harness structurally cannot catch.
