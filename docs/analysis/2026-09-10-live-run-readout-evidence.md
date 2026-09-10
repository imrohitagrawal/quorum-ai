# Live run 1 — evidence for the #290 readout fixes
build_sha c40b2e12f3e8bb5edd021ac8a96d2a3642c7b1e8   (== merge SHA)
query_run_id 5a9c2d63-73ad-45de-b8be-c67c2ddef66e
finished 2026-09-10T06:18:58Z  |  2m49s  |  actual $0.094 (approved $0.076)

## 1.4 — round 2 is announced WHILE it runs (ADR-0108)
Stage strip, sampled mid-run:
  * Initial answers   4/4 answers - Initial model answers collected.
  * Debate round 1    completed - Debate round 1 completed.
  * Debate round 2    running   - Running debate round 2.
  * Synthesis         pending
  pill: "Running - debate round 2 of 2"
Before the fix this state was unobservable: the transitions fired in a
stage_delay_ms=5ms burst against a 750ms poll.

## Review blocker fix — round 1's card during round 2
  Round 1 card: state=completed, "complete",
    body = "This round has finished; its critique is being recorded."
Without the `completed` key added in the review round, that card would have
read "This round has not started yet." while the strip said completed.

## 1.5 — the flattened digest is off the display path (ADR-0107)
  #result-debate .transcript-round-body  = 0     (digest suppressed)
  #result-debate .transcript-critic-body = 8     (4 critics x 2 rounds, full text)

## 1.2 — critics are named, not slugged (ADR-0107)
  Slot 1 - GPT-4o-mini
  Slot 2 - Claude Haiku 4.5
  Slot 3 - Gemini 2.5 Flash
  Slot 4 - Nemotron 3 Nano 30B A3B
  (no raw vendor/model-id slug reached the label)

## 1.1 — the count rule, live (ADR-0106)
  coverage 2 of 4 -> required max(1, 4-1) = 3 -> NOT MET (correct)
  caution line: "Only 50% of the answers that came back carried a primary
    source - treat this as provisional."
  caption: "2 of 4 responding models returned visible source references."
  The synthesis acted on the VERDICT, not a percentage:
    "...because the source-coverage target was NOT MET, pause for a human
     review/audit of the original sources..."
  That is the rewritten prompt working: the model was told the verdict the
  application computed rather than asked to re-derive it from a rounded number.

## 1.3 — the trust number is explained (ADR-0109)
  state=verified band=high, "92 of 100 - high trust"
  basis: "A weighted blend of seven automated checks on this run's own output.
          It is not a judgement of whether the answer is correct."
  "Checks fully met:"  (6)
    Citation markers point at a listed source
    Every answer came from a live model
    Every model slot produced a usable answer
    Dissent was preserved, not flattened
    Open uncertainty was flagged
    Framed as decision support
  "Checks that fell short:"  (1)
    Not every answer that came back carried a primary source.
  6 met + 1 short = 7 signals, all accounted for on this run.
  The shortfall list has its OWN lead - the review finding (failure bullets
  visually owned by "Checks fully met:") is fixed and confirmed live.

## 1.6 — REFUTED on live data, measured
Per-slot answers (.transcript-opening), all four:
  slot 1: 3153 chars,  9 paras, 1 list/7 items, 0 headings, 7 strong, 7 links
  slot 2: 2944 chars,  8 paras, 2 lists/6 items, 6 headings, 5 strong, 7 links
  slot 3: 4081 chars,  8 paras, 1 list/6 items, 0 headings, 6 strong
  slot 4: 5465 chars,  3 paras, 2 lists/12 items, 2 headings, 41 strong
  rawMarkdownInText: [] on ALL FOUR  (no literal ** ## - ](http in any text node)
  endsMidSentence: false on ALL FOUR (nothing truncated)
  longest unbroken run 373-695 chars (normal paragraph, not a wall)
The original "per-slot answers are a wall of text" claim does NOT reproduce
against the deployed build.

## Honest note
Coverage came back 2 of 4, which MISSES under both the old 0.80 threshold and
the new count rule - so this run confirms the MECHANISM (verdict-keyed prompt,
caution line, caption) but does NOT discriminate old rule from new. A 3-of-4
run would; that is what runs 2 and 3 may or may not produce, and it is not
something to arrange.

---

# Live run 2 — THE DISCRIMINATING RUN
query_run_id fcca9510-4b29-4c5a-92a0-a25a55c07f07   |  actual $0.04
question: "Which onboarding metrics actually predict 12-month SaaS retention,
           and which are vanity metrics?"

coverage: **3 of 4** responding models returned visible source references.

  OLD rule (0.80):  3/4 = 0.75 < 0.80  -> NOT MET -> caution line, "provisional",
                    synthesis told to pause for human review.
  NEW rule (count): 3 >= max(1, 4-1) = 3 -> MET -> no caution line.

  OBSERVED: no `.result-verdict-coverage` element. Target met.

This is ADR-0106's whole case, occurring naturally on a paid production run:
the rule change flips the verdict on a real 3-of-4 run, in the direction
intended. Run 1 (2 of 4) missed under both rules and so could not discriminate.

Trust panel, same run:
  "Checks that fell short:" still lists "Not every answer that came back carried
  a primary source." That is CORRECT and not a contradiction: the coverage
  SIGNAL is 0.75 (< 1.0, so it costs composite points) while the run-level
  TARGET is met. Two different quantities, both reported honestly.

Also confirmed again on this run:
  transcript-round-body  = 0    (digest still off the display path)
  transcript-critic-body = 8    (full per-critic text)
  critic labels          = display names, no vendor/model-id slug
  session trail          = 2 entries

---

# Live run 3 — FAILED UPSTREAM, and a live instance of issue #105
query_run_id 93ba6be1-918c-4c46-aad1-9cd15517b3c7
status partial | live_count 0 | local_count 0 | demo_mode false
all four slots: failed / PROVIDER_UNAVAILABLE / openrouter_search
failed_steps: initial_answers, debate_round_1, debate_round_2, synthesis
elapsed 0.3s

Cause is transient and upstream, not us:
  prod /ready          -> state "live", no reasons, ceiling NOT reached
  openrouter.ai/models -> HTTP 200 in 0.21s (checked right after)
Most likely a burst rate-limit: three runs inside ~11 minutes, each dispatching
4 answers + 8 critics + synthesis. NOT the spend ceiling ($0.2092 of $5.00).

## The part worth keeping: it was CHARGED for producing nothing
  actual_cost_usd "0.0758"   cost_source "estimated"
  global_daily_spend_usd moved 0.134 -> 0.2092 (+0.0752, matches)

A run where every slot failed with PROVIDER_UNAVAILABLE and live_count is 0
still books ~$0.076 against the daily meter, from the ESTIMATE rather than
measured usage. That is exactly open issue #105 ("E1: 5xx is classified as
possibly-billed on a premise with no evidence - close it with data"), and this
is the data: a real, dated, reproducible instance.

NOT YET ESTABLISHED, and it is the whole question: whether OpenRouter actually
billed anything for those four calls. The telemetry rows for this run_id settle
it, and reading them needs the Fly harvest. Do not conclude "money leak" or
"correct conservative accounting" without them.

---

# 1.7 — session trail, confirmed with THREE nested runs
Trail (newest first):
  1. "How should a seed-stage SaaS team sequence onboarding fixes..."
  2. "Which onboarding metrics actually predict 12-month SaaS retention..."
  3. "What are the strongest evidence-based interventions for reducing..."

Restored OLDEST  -> run 1's own question   (old code: would show run 3's)
Restored MIDDLE  -> run 2's own question
Restored NEWEST  -> run 3's own question
Each restored #result-question equals the entry's FULL `title` attribute, so
the complete question is stored and the 80-char label is render-only.
Restoring in sequence (oldest -> middle -> newest) kept each correct, which is
the COMPOUNDING half of the defect: the old code wrote the wrong value back,
so restoring A then B mislabelled B with A's question.
