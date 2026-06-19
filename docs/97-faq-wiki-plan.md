# FAQ Wiki Plan

Status: Git draft only. Owner: documentation. Evidence: `docs/study/00-study-index.md`, `docs/01-product-brief.md`.

## Purpose

Create a plain English FAQ/wiki for Quorum AI that helps newcomers understand the product, the AI workflow, the safety boundaries, and the evidence needed before release.

## Proposed FAQ Sections

| Section | Questions To Answer | Evidence |
|---|---|---|
| Start here | What is Quorum AI? Who is it for? What is built now? | `docs/study/M0-read-this-first.md` |
| Product | What problem does it solve? What is the MVP? What is out of scope? | `docs/study/M1-problem-and-mvp.md` |
| AI workflow | Why four models? What are critique rounds? What does synthesis mean? | `docs/study/M2-ai-solution-and-work-easing.md` |
| Safety | Why is this decision support only? What high-stakes warnings exist? | `docs/42-ai-safety-grounding.md` |
| Security/privacy | How are provider keys protected? Why warn against private data? | `docs/40-threat-model.md`, `docs/43-privacy-data-governance.md` |
| Architecture | What are the main components and data boundaries? | `docs/20-architecture.md`, `docs/23-data-model.md` |
| Testing | How will acceptance criteria be tested? What evidence is missing? | `docs/54-ac-to-test-map.md`, `docs/57-test-evidence.md` |
| Operations | What must operators watch after release? | `docs/80-observability.md`, `docs/83-runbook.md` |

## Answer Standard

Every answer should explain what the concept is, why it matters, how it works in this project, what evidence exists, and what is still planned.

Each answer must include a project example from Quorum AI and a real-life analogy that helps a newcomer understand the concept without losing technical accuracy.

## Publication Rule

Keep the FAQ in Git until the user approves the exact Confluence or public page payload.
