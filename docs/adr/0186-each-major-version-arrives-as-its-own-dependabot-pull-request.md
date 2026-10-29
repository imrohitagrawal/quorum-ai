# ADR-0186: Each major version arrives as its own Dependabot pull request

## Status

Accepted — 2026-10-29, board rows W118 and W122. It carries out the product owner's decision
CHG-105.

**Supersedes**, without editing it (`docs/README.md`: "superseded never edited"): ADR-0185,
decision 1, the clause "major versions are ignored". The rest of ADR-0185 stands.

## Context

ADR-0185 grouped minor and patch updates and told Dependabot to ignore major versions, so that one
breaking change could not hold back a whole group. Ignoring them did more than that: Dependabot
never proposes an ignored version, so nothing would ever say a major was available.

The cost is visible today. Five of the six actions the workflows pin target Node 20, two or more
major versions behind their latest releases, and main's CI already carries GitHub's warning that
Node.js 20 is deprecated and that those actions are being forced onto Node 24. An ignored major
would leave that to be noticed by hand.

## Decision

1. No `ignore` rule for major versions. Each group still takes only minor and patch updates, so a
   major falls outside every group and Dependabot opens it as its own pull request, on the same
   monthly schedule and 7-day wait.
2. Each such pull request is its own work item: its release notes and breaking changes read, its
   own CI run green, and, for an action, the pin kept to a full commit.
3. Board row W122 tracks the five actions on Node 20.

`tests/unit/test_w118_repository_hygiene_files.py` fails if any entry ignores major versions.

## Alternatives rejected

- **Keep ignoring majors and track them by hand.** A list kept by hand goes stale; the bot already
  knows every release.
- **Majors inside the groups.** One breaking change would block every other update in the group
  (ADR-0185).

## Consequences

- More pull requests: one per major per dependency, at most monthly per dependency.
- A major is never silent: it waits as an open pull request until it is taken or closed with a
  reason.
