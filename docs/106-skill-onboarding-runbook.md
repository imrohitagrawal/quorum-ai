# Skill Onboarding Runbook

Use this runbook whenever a new skill is proposed from skills.sh, GitHub, an official vendor, a teammate, or a generated local skill.

## Step 1 — Discover

Run:

```bash
make skill-discover
```

Then classify the need:

- product discovery / PM;
- AI PM / evaluation / grounding;
- coding / architecture / testing / review / ship;
- design / UI / UX;
- database / cloud / platform;
- content / FAQ / LinkedIn / technical article;
- browser/media automation;
- session management / handoff / worktrees.

## Step 2 — Capture provenance

Record:

- source URL;
- owner/repository/path;
- commit/ref/version if available;
- license;
- install command;
- supported agents;
- required permissions;
- review owner;
- review date.

## Step 3 — Audit before use

For a local folder:

```bash
python scripts/audit_external_skill.py path/to/skill-folder
```

Reject or sandbox if the skill asks for secrets, broad shell access, external writes, deployment, destructive git operations, or unbounded network access without a clear reason.

## Step 4 — Decide activation mode

Default mode is `reviewer-only`. Promote only with human approval.

Allowed modes:

```text
discovery-only
reviewer-only
sandbox
workspace-approved
local-wrapper
rejected
```

## Step 5 — Register

Update `configs/external-skill-registry.json` through `external-skill-onboarding-manager`.

Every entry must include: source, purpose, trigger, trust tier, allowed operations, forbidden operations, activation mode, validation command, and owner.

## Step 6 — Route

Map it into `configs/skill-router.json` only after approval. One local driver still owns the artifact. External skills are reviewers unless promoted through a local wrapper.

## Step 7 — Evaluate

Run a small sample task and compare quality before/after. Keep the skill only if it improves output without increasing safety or maintenance risk.

## Step 8 — Review periodically

Re-check stale skills, archived repos, changed licenses, new security advisories, and better alternatives.
