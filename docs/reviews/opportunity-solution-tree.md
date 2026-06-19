# Opportunity Solution Tree Review

## Desired Outcome

Reduce hallucination risk for public users who currently compare multiple AI chatbots manually.

Primary metric: hallucination-risk reduction.

Supporting metrics:

- Answer quality/confidence.
- Cost per query.
- Time saved.
- Citation coverage.

## Opportunity Tree

```text
Outcome: Reduce hallucination risk for important AI-assisted work
|
+-- Opportunity 1: Users need to compare multiple model perspectives without manual chatbot hopping
|   |
|   +-- Solution: One query runs across four configurable OpenRouter-backed model slots
|   +-- Solution: Side-by-side model outputs with visible model identity and source links
|   +-- Experiment: Compare workflow time against manual four-chatbot baseline
|
+-- Opportunity 2: Users need to understand where models agree and disagree
|   |
|   +-- Solution: Consensus and disagreement sections in final synthesis
|   +-- Solution: Two debate/critique rounds before synthesis
|   +-- Experiment: Test one debate round versus two debate rounds for quality and cost
|
+-- Opportunity 3: Users need credible source support
|   |
|   +-- Solution: OpenRouter search first
|   +-- Solution: Tavily or another free search fallback
|   +-- Solution: Mark partial or weak source coverage
|   +-- Experiment: Review whether source links support material claims
|
+-- Opportunity 4: Public usage needs cost and abuse control
|   |
|   +-- Solution: Account required before query execution
|   +-- Solution: One active query at a time per account
|   +-- Solution: Cost estimate, warning, and block thresholds
|   +-- Solution: Optional BYO OpenRouter key for more usage
|   +-- Experiment: Test user understanding of cost warnings and BYO option
|
+-- Opportunity 5: High-stakes and sensitive-data risks need clear boundaries
    |
    +-- Solution: Decision-support-only warning for high-stakes topics
    +-- Solution: Sensitive/private data warning before query submission
    +-- Solution: Defer safe-sensitive-data claims until privacy controls exist
    +-- Experiment: Test warning comprehension before requirements sign-off
```

## Prioritized Bets

| Bet | Opportunity | Why Now | Risk | Experiment |
|---|---|---|---|---|
| Four-model single-query workflow | Compare multiple perspectives | This is the core product promise. | Provider/model failure. | Prototype with selected default models. |
| Consensus/disagreement synthesis | Understand agreement and uncertainty | Highest link to hallucination-risk reduction. | Synthesis may hide important nuance. | Rubric review of synthesis outputs. |
| Two debate/critique rounds | Improve answer confidence | Product owner selected it as core workflow. | Latency and cost. | Compare one-round versus two-round outputs. |
| OpenRouter-first search with fallback | Credible source support | Source links are required for trust. | Search quality varies. | Source support review. |
| Account plus one-active-query limit | Cost and abuse control | Public launch needs spend protection. | Signup friction. | Usability test of account and run flow. |
| Optional BYO OpenRouter key | More usage path | Allows heavier users without expanding app-funded cost. | Secret handling and support complexity. | Architecture/security review plus UX copy test. |

## Assumptions

- OST-ASSUMP-001: Users will prefer an integrated comparison workflow over manually opening four chatbots.
- OST-ASSUMP-002: Consensus/disagreement presentation is more valuable than simply choosing the best model answer.
- OST-ASSUMP-003: Two critique rounds improve confidence enough to justify added cost and latency.
- OST-ASSUMP-004: Users will understand the difference between app-funded default usage and optional BYO OpenRouter usage.

## Risks

- OST-RISK-001: Model debate can produce plausible but unsupported criticism.
- OST-RISK-002: Synthesis can over-compress disagreement.
- OST-RISK-003: Source links can be present but not actually support claims.
- OST-RISK-004: Public users may ignore high-stakes and sensitive-data warnings.

## Experiments

| ID | Experiment | Method | Decision It Informs |
|---|---|---|---|
| OST-EXP-001 | Manual baseline comparison | Compare time and confidence against four separate chatbot runs. | Whether MVP saves enough time. |
| OST-EXP-002 | Debate depth evaluation | Score one-round vs two-round outputs against quality/cost rubric. | Whether two rounds remain in MVP. |
| OST-EXP-003 | Source support audit | Review material claims against linked sources. | Citation acceptance criteria. |
| OST-EXP-004 | Warning comprehension test | Ask users to explain safety/privacy warnings before continuing. | Warning copy and acknowledgement rules. |
| OST-EXP-005 | Cost/BYO comprehension test | Ask users to choose between app quota, model change, or BYO key. | Account/API-key UX requirements. |
