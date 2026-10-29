# ADR-0184: Public records are restatements, and the public-content guard is shared

## Status

Accepted — 2026-10-29, board row W117. It carries out the product owner's decisions CHG-102
(public records restate decisions) and CHG-104 (one shared public-content guard). Moving the
secret scan ahead of the unit tests is an engineering choice made in W117.

## Context

This repository is public. Until CHG-102, its rules asked for each owner decision to be recorded
in the owner's exact words with the session it came from (`AGENTS.md`, "Decisions"; the delivery
skill's inputs, prose auditor and quality bar; the next-session prompt template; the
`docs/README.md` row for decisions). Following those rules put quoted conversation and session
identifiers into public files.

Text published outside the tree (pull-request bodies, issue comments, merge messages) passes no
scan at all. `scripts/security_scan.py` reads only the files git could commit.

A scanner for this text was planned here, built from `scripts/security_scan.py`. A review of its
written plan found five blocking gaps:

| Gap | Example |
|---|---|
| The destination | visibility read from `origin`, while `git push other` or `gh api repos/OWNER/OTHER/...` writes elsewhere |
| What a push sends | the current branch scanned, while `git push origin other:main`, `--all` or tags send other commits; `git log -p` leaves out merge resolutions |
| Text outside the command line | `gh pr merge --body-file`, release notes, text typed in an editor |
| An override | the term list found through an environment variable an agent can point at an empty list |
| The scan itself | an example line in the plan that the existing secret scan rejects |

A shared guard built outside this repository was already in review and handles the first three.
Measured against a shared test set (planted values that must be blocked, clean text that must
pass): it blocks home paths, personal email addresses, GitHub tokens, AWS key ids, private-key
blocks and every private term, in 68 ms a scan. It misses tool and transcript identifiers,
session links and OpenRouter keys, and an environment variable can switch its term list off;
those findings went to its maintainers.

## Decision

1. A public record states the decision, its basis and its trade-offs, with the date. It quotes no
   one and carries no session identifier or internal discussion. The exact record stays in the
   owner's private notes. The four places that required exact words now say this.
2. This repository builds no public-content scanner. It adopts the shared guard when it is
   released: its CI step (advisory first) and a scan of the merge text in `make close-guard`.
3. The secret scan (`make security-scan`) runs first after the install step of
   `validate-and-test`, before the unit tests.

## Alternatives rejected

- **Build this repository's own scanner as well, and compare.** Two scanners drift apart, and
  the planned one had the five gaps above to close before it could be trusted. The shared test
  set gives the comparison's value without the second build.
- **Keep exact words in public rows.** It is the cause of the content this work removes.

## Consequences

- Until the shared guard is released, text is checked by hand with it before each publish.
- A reader can no longer compare a CHG row with the wording of the answer it records.
- A committed key or home path fails `validate-and-test` before the unit tests (the full suite took 14 minutes
  21 seconds in a local `make quality` run on 2026-10-29); `tests/unit/test_w117_secret_scan_runs_before_tests.py` pins the order.
- The files here from before CHG-102 that quote the owner are moved out by the cleanup of the
  existing public records (CHG-103), not by this change.
