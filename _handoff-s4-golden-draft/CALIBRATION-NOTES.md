# S4 Golden Set — Calibration Notes

All thresholds in `src/product_app/evaluation.py` are **ADVISORY** until this
golden set calibrates them. These notes map each advisory constant to the golden
cases that constrain it and to what a calibration run would measure.

**No new threshold values are proposed here — that requires the measurement
run.** These notes only identify which cases bracket each constant and what the
run should compute, so a human + measurement can decide any change.

The calibration run is: load all 78 cases through the hermetic runner
(`judge=None`), record each case's measured `citation_marker_grounding`,
`live_ratio`, `completeness`, `refusal` fractions, and
`diagnostics.layer_a_composite_unverified`, then check that the current
thresholds reproduce every case's asserted `expected` label/band and measure the
margin by which each boundary case clears the cut.

---

## GROUNDING_FABRICATION_THRESHOLD = 0.5  (`evaluation.py:741`)

Splits `unfaithful`/`high-risk` (grounding < 0.5) from
`faithful`(-or-partial)/not-high (grounding ≥ 0.5).

**Cases immediately BELOW (must stay unfaithful/high):**
- `fabrication-grounding-01` (0.0), `-02` (0.333), `-04` (0.333, placeholder host), `-07` (0.444, DEBT-011 synthesis ordinals)
- `polar-disagreement-04` (0.0), `noise-sensitivity-pairs-02` (0.0), `-04` (0.0)
- `low-citation-obscure-02` (0.0), `-06` (0.20, placeholder host)
- `high-stakes-03` (0.25), `-07` (0.0, simulated)
- `refusal-expected-02` (0.417), `adversarial-injection-02` (0.412), `-06` (0.222)
- `time-sensitive-02` (0.056)

**Cases immediately ABOVE (must stay ≥0.5 → not unfaithful):**
- `fabrication-grounding-08` (**exactly 0.5** — the inclusive-boundary pin), `-03` (0.667)
- `factual-consensus-03` (0.6), `polar-disagreement-08` (0.667)
- `low-citation-obscure-04` (0.667), `ambiguous-multi-hop-08` (0.692), `time-sensitive-07` (0.667)

**Tightest bracket:** `refusal-expected-02` (0.417) and `fabrication-grounding-07`
(0.444) below vs `fabrication-grounding-08` (0.500) on the line and
`factual-consensus-03` (0.600) above. A calibration run measures the gap between
the highest unfaithful grounding and the lowest faithful grounding across the
corpus, and confirms 0.5 falls strictly inside it (currently 0.444 | **0.500** | 0.600).

---

## GROUNDING_GOOD_THRESHOLD = 0.8  (`evaluation.py:761`)

Splits `low` risk (grounding ≥ 0.8) from `medium` risk (0.5 ≤ grounding < 0.8).

**Cases immediately BELOW (must be medium):**
- `factual-consensus-03` (0.6), `polar-disagreement-08` (0.667), `high-stakes-08` (0.70)
- `fabrication-grounding-03` (0.667), `-08` (0.5), `low-citation-obscure-04` (0.667)
- `ambiguous-multi-hop-08` (0.692), `time-sensitive-07` (0.667, faithful+medium straddle)

**Cases immediately ABOVE (must be low):**
- `adversarial-injection-03` (0.875), `-04` (0.875), `-07` (0.882), `-01` (0.947)
- `low-citation-obscure-03` (0.889), `factual-consensus-02` (0.917), `polar-disagreement-01` (0.917), `-03` (0.923)
- `noise-sensitivity-pairs-01` (0.958); several at 1.0 (`FC-01`, `FC-05`, `HS-01`, `TS-01`, …)

**Tightest bracket:** `high-stakes-08` (0.70) / `ambiguous-multi-hop-08` (0.692)
below vs `adversarial-injection-03`/`-04` (0.875) and `low-citation-obscure-03`
(0.889) above. A calibration run measures whether any case sits in the
0.70–0.875 gap (none currently does) and confirms 0.8 separates the two risk
bands cleanly. `time-sensitive-07` is the case most sensitive to any move of
this constant (deliberate faithful/medium straddle at 0.667).

---

## BAND_LOW_CEILING = 50.0  /  BAND_MODERATE_CEILING = 75.0  (`evaluation.py:766-767`)

These band the **TrustScore composite** into low/moderate/high. **With
`judge=None` (the CI posture) `support_verified=False`, so `score=None` and
`band="unverified"` on every one of the 78 cases** — no hermetic golden case
exercises these two ceilings.

**What constrains them:** nothing in this set directly. They can only be
calibrated by the **opt-in nightly with the judge ON** (DeepEval + RAGAS
vocabulary), where a real `score` is produced. A calibration run under
`judge=None` should assert that all 78 cases return `band="unverified"`,
`score=None`, and populate only `diagnostics.layer_a_composite_unverified` —
i.e. confirm these ceilings are *not* reachable in CI. Activating/changing them
is queued to the human + the judge-on measurement run, per the
guardrail-measurement rule.

---

## REFUSAL_MAJORITY_THRESHOLD = 0.5  (`evaluation.py:430`)

`refusal_detected = refusals / len(substantive) >= 0.5`.

**Boundary pins (exactly 0.5, must FIRE on `>=`):**
- `refusal-expected-05` (2 of 4 substantive decline)
- `ambiguous-multi-hop-07` (2 of 4 substantive decline)

**Above 0.5 (fire), with the failed-slot denominator subtlety:**
- `high-stakes-04` (2 of 3 substantive; slot 4 failed, excluded)
- `refusal-expected-03` (2 of 3; failed slot excluded), `-02` (3/4), `-04` (3/4, apology-skip)
- `low-citation-obscure-05` (3/4), `adversarial-injection-05` (3/4)
- Wholly-refused (4/4): `refusal-expected-01`, `-06`, `-07`, `high-stakes-09`

**Must NOT fire (0 refusals):** every non-refusal case (all consensus, polar,
grounded high-stakes, injection-resisted cases).

A calibration run measures, for each case, `refusals / len(substantive)` and
confirms the `>= 0.5` boundary reproduces `refusal_detected` for the two
exactly-0.5 pins and excludes failed/empty slots from the denominator
(`high-stakes-04`, `refusal-expected-03`). It also confirms `run_wholly_refused`
(`refusals == len(substantive)`) fires only on the four 4/4 cases.

---

## LAYER_A_WEIGHTS  (`evaluation.py:691-706`)

The per-signal weights combined into `layer_a_composite_unverified`
(`compute_composite`, `evaluation.py:1314-1348`), with weights of `None`-valued
signals dropped and the remainder renormalised.

**Cases exercising renormalisation (grounding = None → composite over 6 signals,
not 7):** `factual-consensus-08`, `polar-disagreement-07`, `time-sensitive-03`,
`-06`, `ambiguous-multi-hop-04`, `low-citation-obscure-01`, `-05`, `-07`,
`refusal-expected-01`, `-03`, `-04`, `-06`, `-07`, `high-stakes-09`,
`noise-sensitivity-pairs-06`, `fabrication-grounding-05`, `adversarial-injection`
(none — all have grounding). Every other case exercises the full 7-signal
composite.

**Cases exercising the `live_ratio`/`completeness` levers on the composite:**
`high-stakes-07` (live_ratio 0.0), `low-citation-obscure-06` (0.25),
`adversarial-injection-07` (0.5), `noise-sensitivity-pairs-08` (0.25/0.75),
`time-sensitive-04` (completeness 0.75), `factual-consensus-06`,
`polar-disagreement-05`, `ambiguous-multi-hop-02` (completeness 0.75).

Note `agreement_ratio` is a REPORTED signal deliberately **excluded** from
`LAYER_A_WEIGHTS`; no case should assert it drives the composite.

A calibration run measures the distribution of
`layer_a_composite_unverified` across the whole corpus and, grouped by asserted
`faithfulness_label`, checks the current weights produce a monotone separation
(faithful > partial > unfaithful on the composite) and reports the overlap, if
any, between adjacent groups. It does **not** set new weights.
