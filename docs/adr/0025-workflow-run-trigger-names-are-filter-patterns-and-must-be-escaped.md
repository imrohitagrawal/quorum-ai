# ADR-0025: `on.workflow_run.workflows` entries are filter patterns, and must be escaped

## Status

Accepted — 2026-08-07

## Context

`deploy.yml` declared:

```yaml
on:
  workflow_run:
    workflows: ["CI", "Tests", "E2E (axe + parity)"]
```

Two of the three fired it. The third never had. Measured 2026-08-03..08-07,
counting a "Deploy to Fly.io" run created within 20s of a required workflow's
completion on a genuine push to `main` (the observed lag is 2-4s):

| required workflow | fired a Deploy run |
|---|---|
| `CI` | 27 / 27 |
| `Tests` | 27 / 27 |
| **`E2E (axe + parity)`** | **0 / 26** |

ADR-0024 recorded this as measured-but-unexplained. The cause is that
**`on.workflow_run.workflows` entries are filter patterns, not literal
strings.** In GitHub's filter-pattern language `+` means *one or more of the
preceding character*, so `"E2E (axe + parity)"` is:

```
E2E (axe   +   one-or-more SPACES   +   ` parity)`
```

which matches the string `E2E (axe  parity)` (two spaces, no plus) and can
**never** match its own workflow's name. `CI` and `Tests` contain no
metacharacters, so they matched literally and carried the entire trigger for
the life of the repository.

It fails silently rather than erroring because the `+` follows a space — a valid
antecedent — so the pattern compiles. (Where there is no valid antecedent, as in
`'C++'`, GitHub instead emits *"Encountered an issue parsing workflow
trigger(s)"* and the trigger dies loudly. This repo got the quiet variant.)

### Proven, not inferred

Because only `deploy.yml` listens for `workflow_run` here, no read-only probe
could settle it — and guessing on the deploy path is exactly what AGENTS.md
rule 8c forbids. So it was measured in a throwaway public repository,
`imrohitagrawal/wfrun-glob-probe`: one upstream workflow named
`E2E (axe + parity)`, and two listeners differing only in escaping.

```
17:41:44  E2E (axe + parity)   push          success
17:41:58  listener-escaped     workflow_run  success      <- +14s
17:42:31  E2E (axe + parity)   push          success
17:42:45  listener-escaped     workflow_run  success      <- +14s

counts: upstream 2 | listener-escaped 'E2E (axe \+ parity)' -> 2
                   | listener-literal "E2E (axe + parity)"  -> 0
```

A positive partner and a negative in one experiment. Corroborated upstream:
`actions/runner#3763` — *"the `workflows` values are treated as glob patterns
and special characters have to be escaped… In the particular case above,
`"C\+\+"` does work."* The behaviour is **undocumented on live docs**;
`github/docs#37022`, which would document it, is still open.

## Decision

Escape filter metacharacters in `on.workflow_run.workflows`, and **single-quote
the entry**:

```yaml
workflows: ["CI", "Tests", 'E2E (axe \+ parity)']
```

Single quotes are not a style choice. `\+` is an invalid escape inside a
double-quoted YAML scalar, measured on this box:

```
"E2E (axe \+ parity)"  ->  ScannerError
'E2E (axe \+ parity)'  ->  'E2E (axe \+ parity)'
```

A double-quoted form would make the whole file unparseable, so `on:` would
resolve to nothing and **every** deploy trigger would die — strictly worse than
the defect being fixed. Note the upstream issue's own suggested `"C\+\+"` has
this bug.

### Two lists, two languages

`deploy.yml`'s entries are **patterns** (escaped). `scripts/deploy_gate.py`'s
`REQUIRED_WORKFLOWS` holds **literal names**, because it compares them against
the `name` the Actions API reports for a run, which is never escaped. Both are
correct and they now differ by a backslash — a near-identical pair that will
drift. Nothing pinned them together (`grep -rn REQUIRED_WORKFLOWS tests/` was
empty); `test_the_scripts_required_list_matches_the_workflows_unescaped` now
does.

## Consequences

- The designed redundancy is restored: three triggers instead of two.
- **No behaviour change to what gets deployed.** The gate already WAITED for all
  three workflows to conclude, so E2E was always enforced — a CI or Tests
  trigger carried it. What was missing was the third path to *starting* the
  gate, which matters when the other two are the ones that fail to fire.
- `deploy.yml`'s header comment ("each of the three workflows completing on main
  fires this") becomes true for the first time.
- Deploys may start marginally later in the case where E2E is the last to
  finish, because a third trigger now arrives then. The per-SHA concurrency
  group collapses it.

## What this does not fix

- **The cause of the 2026-08-07 no-run incident is still UNVERIFIED.** That
  merge produced no run of *any* workflow, which is upstream of this bug.
  ADR-0024's third-failure-mode section still stands.
- **Whether `(` and `)` also need escaping is UNVERIFIED.** They are not in the
  documented metacharacter set and the probe matched with them unescaped, so
  they appear literal. The test guards `+ * ? [ ]` only.

## Rejected alternatives

**Rename the workflow to remove the `+`.** It would work, and it is a worse
answer: the name is user-visible in branch protection (`e2e axe + parity
(chromium)` is a required context), so renaming risks detaching a required
status check from its job. Fixing the reference is local; renaming is not.

**Leave it — the gate waits anyway.** This was tempting because nothing is
broken downstream. But it leaves a documented contract false, and it leaves the
whole trigger resting on two workflows while the file claims three. The next
person to debug a missing deploy would be reading a comment that lies.

**Escape it but keep double quotes**, per the upstream issue's own example.
Measured to be a `ScannerError`; it would stop every deploy.
