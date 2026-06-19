# Skills.sh and External Skill Research Snapshot

This file records the factory's current research model for external skills. It is a snapshot, not a permanent allowlist. Refresh before major adoption.

## What the ecosystem provides

Skills are reusable procedural capabilities for AI agents. The skills.sh directory lists skills across multiple agents including Claude Code, Cursor, Codex, GitHub Copilot, Windsurf, Gemini, Cline, Antigravity, VS Code, and others.

## Topics to monitor

| Topic | Why it matters to this factory | Typical adoption mode |
|---|---|---|
| Agent workflows | planning, debugging, worktrees, subagents, handoff, verification, branch closing | reviewer-only or sandbox |
| Testing | TDD, Playwright, verification before completion, web app testing | reviewer-only or local-wrapper |
| Design & UI | frontend design, visual polish, design systems, UI critique, accessibility | reviewer-only |
| Databases | Postgres/Supabase/Firebase/Neon/schema/migration patterns | reviewer-only or local-wrapper |
| React/Next.js/Mobile | framework-specific implementation guidance | tool-specific reviewer |
| Marketing/content | SEO, copywriting, LinkedIn, article, launch content | reviewer-only |
| Cloud/provider skills | Azure, Supabase, Firebase, Vercel, platform operations | sandbox or local-wrapper |
| Browser/media automation | screenshots, browser flows, images, video/GIF pipelines | sandbox only |

## Candidate sources to track

| Source | What to borrow | Trust posture |
|---|---|---|
| skills.sh `find-skills` | dynamic discovery of relevant skills | discovery-only until audited |
| Obra Superpowers | planning, TDD, debugging, worktrees, subagents, verification, branch closing | reviewer/sandbox through local session rules |
| Addy Osmani agent-skills | SDLC define/plan/build/verify/review/ship/code-simplify discipline | reviewer/local-wrapper |
| Paweł Huryn PM Skills | discovery, strategy, prioritization, launch, growth, AI shipping kit | reviewer for product artifacts |
| Dean Peters Product Manager Skills | PRDs, PM workflows, stakeholder questions, product structure | reviewer for PM artifacts |
| Erik Holmberg AI PM Toolkit | AI/ML PM prompts, templates, eval/risk thinking | reviewer for AI product artifacts |
| Dr. Marily Nika AI PM education | AI product framing, evaluation, scaling, portfolio thinking | learning/reference input |
| Vercel Labs agent-skills | web/design/react/Vercel implementation patterns | reviewer/tool-specific |
| Wednesday AI Agent Skills | repo-specific AI onboarding, dependency graph, multi-agent setup | sandbox/reviewer |
| agentskills/agentskills | open skill format and packaging expectations | format reference |
| UI/UX Pro Max | UI/UX review, design intelligence, accessibility/taste checks | reviewer-only |
| Microsoft/Azure skills | Azure Foundry, cloud, identity, observability, cost, infra | sandbox/local-wrapper |
| Supabase/Firebase/Neon skills | database and backend platform patterns | reviewer/local-wrapper |
| Matt Pocock skills | grill/critique, TDD, PRD/issues, codebase architecture | reviewer-only |
| Anthropic official skills | frontend, webapp testing, skill creator, document formats | reviewer/tool-specific |

## Expert rules

- Do not limit the factory to sources the user has mentioned.
- Use marketplace popularity only to decide what to inspect first.
- Prefer audited, official, narrow, well-scoped skills.
- Reject or sandbox skills with broad shell/network/secrets/deployment powers.
- Keep a local wrapper when enterprise governance, Jira/Confluence, release evidence, or regulated data is involved.


## marketplace rank

Use marketplace rank only as a discovery signal. It is not proof of correctness, security, freshness, license safety, or enterprise fit.
