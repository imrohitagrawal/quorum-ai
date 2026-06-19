# ORBI Codex Execution Plans

Use an ExecPlan for complex features, multi-step implementation, architecture changes, or any work expected to touch more than a few files.

An ExecPlan must be self-contained and updated as work progresses. It should allow Codex or a human reviewer to restart from the plan alone.

Each ExecPlan should include:

## Purpose / Big Picture
Explain the user-visible outcome and why the work matters.

## Current State
Summarize the repository state and relevant existing files.

## Target State
Describe the behavior, artifacts, and verification evidence expected after completion.

## Product Identity
Include Product, stableKey, riskTier, Workstream, Release Target, and AI Capability.

## Milestones
Break the work into small vertical slices. Each milestone must have observable validation.

## Progress
Maintain a checklist of completed and remaining work.

## Decisions
Record decisions, alternatives considered, and why the chosen approach was selected.

## Validation
List commands, tests, manual checks, and expected results.

## Risks / Rollback
Capture risks, mitigations, and rollback/disable path.

## Evidence Links
Link PRD, SRS/SSD, ADR, Jira-ready issues, quality gate, runbook, and learning notes where relevant.
