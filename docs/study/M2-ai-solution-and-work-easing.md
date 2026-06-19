# Module 2 - AI Solution And Work Easing

Status: Git draft only. Owner: product/engineering. Evidence: `docs/20-architecture.md`, `docs/42-ai-safety-grounding.md`.

## How it solves the problem using AI

Quorum AI is planned to use four model slots, source-backed answering, two critique rounds, and final synthesis. Instead of asking users to manually compare models, the system orchestrates the comparison and makes agreement, disagreement, source support, and uncertainty visible.

## Where AI Is Grounded

The planned workflow attempts OpenRouter search-backed answering first. If search fails or lacks usable sources, the architecture allows Tavily or another approved fallback provider. Source links are preserved near model answers and used in final synthesis evidence.

## Where human approval is required

The final output is decision support. The user still decides what to trust, whether sources are adequate, and whether a high-stakes topic requires a professional.

## How it eases human work

- One query replaces repeated copy/paste across multiple chatbots.
- Model answers remain distinguishable, so users can audit differences.
- Debate rounds surface weak support and missing reasoning.
- Synthesis saves the user from manually stitching a final answer together.
- Cost and provider failures are visible rather than hidden.

## What AI Must Not Do

- It must not claim guaranteed factual correctness.
- It must not erase material disagreement.
- It must not present high-stakes recommendations as professional advice.
- It must not reveal provider keys or hidden system configuration.
- It must not follow instructions embedded in retrieved web content.

## Risks And Controls

| Risk | Control | Evidence |
|---|---|---|
| Hallucinated answer | Source-backed answers, citation coverage eval, disagreement preservation | `docs/42-ai-safety-grounding.md` |
| Prompt injection from retrieved pages | Treat retrieved content as untrusted evidence | `docs/40-threat-model.md` |
| False consensus | Required disagreement and uncertainty sections | `docs/54-ac-to-test-map.md` |
| High-stakes misuse | Warning and decision-support framing | `docs/11-non-functional-requirements.md` |
| Provider cost surprise | Estimate, confirmation, and block thresholds | FR-005, NFR-002 |

## Evidence

- AI safety and grounding plan: `docs/42-ai-safety-grounding.md`.
- Threat model: `docs/40-threat-model.md`.
- Test map: `docs/54-ac-to-test-map.md`.
- Release evidence status: `docs/73-release-evidence.md`.
