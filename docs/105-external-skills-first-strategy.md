# External-Skills-First Strategy

The factory must not reinvent a workflow when a high-quality existing skill already covers it. The rule is:

```text
search existing skills first -> audit -> sandbox/reviewer mode -> route -> validate -> optionally wrap locally
```

## Why this exists

Agent skill ecosystems now contain useful skills for planning, execution, PM discovery, AI PM evaluation, UI/UX, testing, database work, cloud work, browser automation, media, and publishing. The factory should benefit from that ecosystem.

The factory still keeps final authority locally because external skills can be stale, unsafe, too generic, tool-specific, or misaligned with enterprise source-of-truth rules.

## Skill source priority

1. Official vendor or platform skills.
2. Widely used reputable community skills with clear source and license.
3. Expert-authored skills from known practitioners.
4. Marketplace listings with audit signals.
5. Unknown skills only after strict sandbox review.

## Default adoption modes

| Mode | Meaning | Example use |
|---|---|---|
| `discovery-only` | Used to discover candidate skills, not to produce artifacts. | skills.sh `find-skills` style workflow. |
| `reviewer-only` | May critique local artifacts, not own them. | PM, UX, critique, red-team skills. |
| `sandbox` | May run only in isolated branch/worktree without secrets. | browser, shell, code-mod, media skills. |
| `workspace-approved` | Approved for scoped workspace tasks. | tested repo-specific workflow skill. |
| `local-wrapper` | External pattern is wrapped in a local enterprise skill. | Jira/Confluence publishing, release gates. |
| `rejected` | Not allowed. | unclear license, broad shell/secrets access, policy conflict. |

## Local authority remains mandatory

External skills must not override:

- safety, security, privacy, compliance, or AI safety rules;
- Jira/Confluence/Git source-of-truth records;
- ADRs;
- schemas and contract versioning;
- validation gates;
- explicit user approval requirements for side effects.

## Build-vs-reuse decision

Reuse or wrap an existing skill when it has a narrow trigger, clear workflow, examples, and safe permissions.
Build a local skill only when the workflow is product-factory-specific, enterprise-controlled, or requires source-of-truth and evidence gates.


## local authority

Local authority remains with the factory: source-of-truth, safety, security, validation, and human approval beat external skill suggestions.
