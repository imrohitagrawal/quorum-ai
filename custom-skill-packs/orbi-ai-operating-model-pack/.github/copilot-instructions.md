# GitHub Copilot Instructions — ORBI AI Product Operating Model

Read and follow `AGENTS.md` for repository-wide rules.

This repo uses ORBI / Orbisynth-AI for new AI product incubation and shared AI operating standards.

Core rules:
- Do not touch Aegis or CiteVyn assets.
- Do not store secrets, credentials, API keys, tokens, private keys, or sensitive data.
- Keep changes small, reviewable, and test-backed.
- Use `PRODUCT_IDEA.md` as the product input file.
- Use `PLANS.md` for durable execution planning.
- Use templates under `templates/` for PRD, SRS/SSD, ADR, Jira-ready issues, quality gates, release readiness, and runbooks.
- Before coding, identify the tech stack, package manager, lint command, test command, build command, run command, repository layout, and CI expectations.
- Produce Jira-ready metadata using Product, stableKey, riskTier, Workstream, Release Target, and AI Capability conventions.

When asked to build a feature, produce a first thin vertical slice instead of a large unverified implementation.
