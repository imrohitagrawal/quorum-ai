# ADR-0181: A new security warning is fixed first, without asking, within the same major version

## Status

Accepted — 2026-10-25. The owner's decision is CHG-092: *"Adopt as suggested (Recommended)"*
(header "Update rule", answered 2026-10-25T09:19:13.316Z). The rule's wording below is the
session's; the choice to adopt it is the owner's.

## Context

`make vuln-audit` (`scripts/vuln_audit.py`, ADR-0164) fails when a library the app locks in
`uv.lock` has a published security advisory. It runs in CI, in the required `validate-and-test`
job, so a new advisory blocks every pull request, main's included, until the library is
updated. Twice in one session that wait went to the owner as a separate question.

## Measured

| Case | Owner's answer | The update | Work that waited |
|---|---|---|---|
| CHG-085: pypdf and certifi | 2026-10-22, 19:22:31Z | #584, 2026-10-22, 20:49:42Z | W87-3 (#583) |
| CHG-086: pypdf 6.21.1 to 6.21.2 | 2026-10-24, 13:18:55Z, asked 2026-10-23, 22:46:54Z | #586, 2026-10-24, 15:03:14Z | W88 (#587) |

- Sources: the CHG rows' times and `gh pr list --state merged`.
- The CHG-086 question waited about 14.5 hours for an answer. Both answers chose the update.

## Decision

When a new advisory makes `make vuln-audit` fail, the session:

1. pauses its item;
2. opens its own pull request that moves the library to the fixed version;
3. runs every gate, plus the tests of the code that uses the library;
4. merges it through `make close-guard` and deploys it, as the session's approvals allow;
5. records a CHG row for the update;
6. resumes its item, after merging main into the item's branch.

It does this without asking only when all of these hold:

- the fix is in the same major version;
- a fixed version exists;
- no test shows changed behaviour;
- the library is not in money or sign-in code.

Otherwise it asks the owner, as before.

## Consequences

- The question that waited 14.5 hours in the CHG-086 case is no longer asked.
- Each update is its own pull request, so a reviewer audits the update alone (`AGENTS.md` rule 17).
- The CHG row that records each update is the owner's trace of what changed without a question.
- A session's approvals still bound the merge and the deploy. The rule adds no approval of its own.

## Known limits

- "Money or sign-in code" is judged by the session. Nothing checks it.
- "No test shows changed behaviour" is only as good as the tests of that library's callers.
- A fixed version can carry an unrelated change that no test covers.

## Rejected alternatives

- **Adopt with no limits** (major versions included; ask only when no fixed version exists).
  The owner did not choose it. The session's reason against it: a major version can change
  behaviour that no test here pins.
- **Keep asking each time.** The owner did not choose it. The session's reason against it: it
  keeps the wait measured above.

## Related

CHG-085, CHG-086, CHG-092; ADR-0164 (the locked image and `vuln-audit`); ADR-0153.
