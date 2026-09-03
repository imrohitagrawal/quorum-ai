# ADR-0096: The debate is evidence-led convergence, not a disagreement inventory

## Status

Accepted — 2026-09-03.

Scope note, worded carefully: this record REFRAMES what the debate stage asks
for, building on ADR-0032, ADR-0063 and ADR-0093. It does not retire any of
them, and the word "supersede" is deliberately absent from this section —
`scripts/live_posture_check.py` treats "supersedes" in a Status block as a
REVOCATION marker, and a first draft of this line tripped it. That check is
right to be strict: "Supersedes X" and "Superseded by X" differ by one letter
and mean opposite things about the record you are reading.

The product owner took decisions 1-5 directly: synthesis reads the REVISED
answers as its primary input, and the self-assessment is a closed set carrying
rationale and sources. The owner's framing is quoted verbatim in Context below;
this record is the design it names.

**Authorises nothing.** It carries no `**Authorises:**` line and may not be
cited to sanction a live-execution posture — going live costs its own ADR
(ADR-0070/0071's rule), and this one only says what the debate should ASK.

## Context

The product owner reviewed the shipped peer critique (#290, ADR-0093/0095) and
described what the debate is *for*, in these words:

> It's not about the rounds or the models trying to prove themselves, but about
> trying to see what is actually correct and what the ideal solution to the
> user's problem should be. They should be working as a unit afterwards to
> ensure that the correctness is provided to the user.

and, on how a position may be defended or changed:

> All the models should be asked to provide answers and support their stance and
> agreement/disagreement based on the verifiable sources so that it becomes easy
> and we do not hallucinate, or the models do not compromise under peer pressure
> or social pressure.

The shipped pipeline cannot express either. Four defects, each verified by
command, not by reading:

### 1. Critics are asked to judge sources they are never shown

`ROUND_ONE_SYSTEM_PROMPT` asks for *"specific points of weak or missing source
support."* `_debate_user_prompt` passes, per answer:

```
- Slot {n} — {label} ({status}): {answer excerpt}
```

`grep -c sources` over `_debate_user_prompt` returns **0**. The synthesis prompt
builder emits a `    sources: …` line per answer; the debate prompt builder does
not. So the lens the round is named after cannot be applied: a critic can only
infer source quality from prose.

### 2. Debate calls cannot search, so a critic has no evidence at all

`ProviderExecutionService.call_with_prompt`'s own docstring: *"Unlike the
per-slot `_live_openrouter_response`, this method does NOT attempt the
`:online` suffix."* Combined with (1), a critic has neither the sources of the
answers it is judging nor any way to look one up. Evidence is not merely
under-supplied — there is none on the call.

### 3. The peer directive forbids a model from reconsidering itself

Added by ADR-0093's build (`debate.py`, `_peer_critic_directive`):

> "You are the model that wrote Slot N's answer. Critique the OTHER slots'
> answers against the lens above. **Do not defend or restate your own answer.**"

The intent was to stop a model burning its token budget re-arguing itself. The
effect is to forbid the one behaviour that makes a debate a debate. This is a
defect introduced by this project, not inherited.

### 4. Every stage measures CONCORD; no stage asks what is CORRECT

- round 1: *"You are a debate moderator… identify specific points of
  disagreement"*
- round 2: *"…the strongest residual disagreements after round 1"*
- synthesis consensus: *"list the 2-4 points where they agree"*

A model could produce a flawless disagreement inventory without once asserting
that a claim is wrong and citing why. And the trust surface compounds it:
`compute_consensus_strength` returns `"strong"` on agreement and the verdict
band paints green on that — so **four models agreeing and being wrong together
reads as the product's highest-confidence state**, which is the exact failure a
multi-vendor panel exists to catch.

ADR-0063 is the same defect one layer up: it removed the "How positions moved"
table because `after_round_1` was a dict lookup on the model's FINAL alignment
and *"nothing in that path reads a round-1 output."* Its stated reason —
*"unobservable — the transcript has no per-model attribution"* — is discharged
by #290, which added exactly that attribution.

## Decision

### 1. Evidence is the currency. A position is only as good as its sources.

Every claim a critic makes, and every position it takes, cites a source or is
explicitly marked unsourced. Unsourced is permitted and VISIBLE; it is never
silently equivalent to sourced.

**What this achieves and what it does not, stated because the difference is
where products mislead.** Three distinct levels:

| Level | Claim | Status here |
|---|---|---|
| L1 | a source is cited | **this record** |
| L2 | the source RESOLVES (real, reachable) | follow-up; the credential-guarded fetcher exists |
| L3 | the source SUPPORTS the claim | not attempted; retrieval + entailment |

A citation is not a verification. Models hallucinate citations — plausible URLs,
real URLs that do not say what is claimed, real papers misattributed. This
record buys L1: it makes an unsourced assertion **visible and costly**, not
impossible. No UI copy may imply otherwise.

### 2. The debate prompt carries each answer's sources

Fixes defect 1, costs nothing but input tokens, and is a precondition for
everything else. Sources are provider-originated and go INSIDE the fenced
untrusted block, exactly as the answers do.

### 3. Round 1 is cross-examination; round 2 is convergence

**Round 1**, each eligible model seeing all four answers and their sources:
- where do we agree, and is that agreement EVIDENCED or a shared assumption?
- where do we differ, and what precisely is the factual disagreement?
- what did another model get right that I missed?
- what did another get wrong, and what is my evidence?

**Round 2**, each model seeing round 1's critiques, reports:
- `self_assessment`: one of `held_agreement`, `held_solution`, `amended`,
  `changed` — a CLOSED set, for the same reason `DEBATE_MODES` is closed
- `rationale`: why, in prose
- `sources`: the evidence for that position
- `revised_answer`: what it now believes the correct answer to be

### 4. Synthesis reads the REVISED answers as its primary input

Owner's decision. The final answer the user reads reflects the panel *after* it
read itself, not before. Without this the debate cannot change the output, and a
debate that cannot change the output is theatre.

The originals are retained and remain rendered — the movement is the evidence
that the debate did something, and hiding the "before" would make the "after"
unfalsifiable.

### 5. A held minority position with sources is a first-class outcome

`held_solution` is not failure. A model that holds against three others AND
cites evidence is the single most valuable signal this product can produce — it
is the case a one-model tool cannot reach. It must be rendered, and it must
prevent an unqualified consensus claim.

This is the anti-sycophancy mechanism, and it is why `sources` is required on a
change: capitulation must cost something. LLMs are documented to capitulate
under social pressure; asking "do you want to change your mind?" after showing
three dissenters produces conformity, not correctness, unless the change has to
be paid for in evidence.

## Consequences

- **Every debate call's completion grows.** Round 2 now returns a structured
  self-assessment AND a revised answer, where it previously returned prose plus
  a stance envelope. `DEBATE_ROUND_MAX_TOKENS = 2000` was sized for a critique
  alone. This is a MONEY change and it lands before the constants pass (W3), so
  W3 must measure the post-0096 shape, not the post-0093 one.
- **The debate prompt grows by the sources of four answers**, on every debate
  call — eight calls under peer critique. Input tokens only.
- **`_peer_critic_directive` is rewritten**, not deleted: a critic still must not
  merely restate its answer, but it must now assess it.
- **`SlotCritique` gains four fields**, so `openapi.yaml` moves and the
  blocking Schemathesis context moves with it.
- **`slot_critiques` must be RENDERED.** Today it is recorded and displayed
  nowhere — `grep` finds it in `app.js` only inside comments — while the receipt
  itemises a paid `(critique)` row per critic. The user is charged per model for
  detail the interface does not show, and the digest they DO see discards 75% of
  each critique at four critics. That is corrected here.
- **The digest stays, for prompts only.** `SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS`
  is a token budget for what we send to a model. A browser has no token budget,
  and applying a prompt bound to a display was a conflation.
- **ADR-0063 becomes revisitable.** Its removal reason was that movement was
  unobservable; `self_assessment` observes it. Restoring that table is NOT done
  here — it is a separate package, and it must read the observation rather than
  re-deriving the inference.

## Rejected alternatives

**Free-text self-assessment.** Rejected by the owner: nothing downstream can
compute from prose, so the positions surface would stay an inference and the
verdict could not use it.

**Closed set with no rationale.** Cheapest and machine-readable, but the user
cannot see WHY a model moved — which is the only thing that distinguishes
evidence from herding.

**Let synthesis read only the originals.** Rejected: the debate would not affect
the answer, so its cost would buy the user nothing but commentary.

**Weight positions by evidence automatically.** Considered for the minority
question and NOT taken: a scoring rule over source counts is easy to write and
hard to explain, and this product's own history (ADR-0083, #382, #394) is a
series of scoring heuristics that had to be undone. Surface the evidenced
dissent; let the human weigh it.

**Enable `:online` for debate calls** so critics can verify independently. Not
taken here — it is a real per-call cost increase on eight calls and belongs with
the L2 work, measured rather than assumed.

## References

- ADR-0032 — the copy-vs-mechanism correction that split #290 out
- ADR-0063 — removed the inferred position table; its reason is discharged here
- ADR-0075 — a strict majority is this product's bar for a panel-level reading
- ADR-0093 / ADR-0095 — peer critique's shape and its rollout gate
- ADR-0094 — the money constants; W3 must now measure the post-0096 shape
