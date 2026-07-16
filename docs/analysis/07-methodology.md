# Category 7 — Methodology (the operating loop)

The process that produced this analysis and should produce the work that follows.

## The loop

```
PLAN thoroughly first
   └─ verify ground truth (read code, run cheap checks, enumerate the population)
LOOP:
   verify → implement → verify → implement
   (each implementation step ends by observing REAL output, not just green tests)
DOCUMENT
   └─ write the decision + evidence into the repo (durable), not chat (evaporates)
```

Concretely, this session followed it: plan approved → 3 parallel Explore agents
established ground truth → built the fixture → **proved the invariant RED** →
wired CI → documented here. No claim was written before it was verified.

## Decompose vertical → horizontal, then measure each

1. **Vertical canonical slices** — cut the work into end-to-end deliverables that
   each stand alone (e.g. "the UI rendering gate", "the search rework", "the cost
   accounting"). Each slice is independently valuable and testable.
2. **Horizontal splits within a slice** — the sub-tasks (fixture, invariant,
   snapshot, smoke, CI wiring) that compose the slice.
3. **Categorize, measure, quality-gate every deliverable** — each row in the
   ledger and machinery tables carries its own *Measurement / prove-red* column;
   a deliverable is not "done" until its gate exists, covers it, and is proven red
   then green.

## Rules that keep the loop honest

- **Verify before asserting** — the fractal root failure was skipping this
  (memory `narrow-sample-wrong-conclusion`). Enumerate the full population.
- **Prove-red before trusting a gate** — a gate not shown to fail on a real defect
  is assumed broken.
- **Real output is the oracle** — observe rendered pixels / real behaviour, not
  DOM assertions or mocked JSON alone (memory `simulated-data-hides-real-bugs`).
- **Document below the line** — the deliverable is repo files, not a chat summary;
  chat evaporates on the next session (this whole analysis exists because of that).
- **Minimize paid runs** — verify cheaply (logs, local sim, e2e, estimate gate);
  spend a real paid run only when nothing cheaper can answer the question
  (memory `minimize-paid-production-runs`).

## Where each methodology element is enforced

| Element | Enforced by |
|---------|-------------|
| verify-first | `/verify` + CI tests defining "done" |
| decompose + measure | the per-deliverable *prove-red* column in these tables |
| document durably | tracked `docs/` files + `git ls-files` |
| prove-red | the committed RED-proven invariant (`03-enforcement-machinery.md`) |

Methodology is Cat 7 because it is the meta-process; its individual rules are
principles (Cat 2) and its artifacts are gates (Cat 3). It ties the categories
into a repeatable operating model.
