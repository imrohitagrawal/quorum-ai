# Start Here — Simple Factory Flow

This product repository is designed to start from a rough idea, not from a finished PRD.

## The simplest path

1. Put your idea in `PRODUCT_IDEA.md`, or tell Codex your idea in chat.
2. Run `make next` to see the suggested next action.
3. Ask Codex: `Start product factory from my idea.`
4. Codex must ask clarifying questions before writing requirements or code.
5. Codex converts answers into `docs/04-problem-statement.md`, `docs/01-product-brief.md`, requirements, acceptance criteria, Jira issues, Confluence guide, test plan, architecture, and release evidence.

## Important rule

The factory should never make you remember a 100-step process. It should always maintain:

- current phase;
- next recommended action;
- questions that need your answer;
- assumptions it is making;
- generated artifacts;
- validation status;
- what to do next.

Use `docs/00-factory-console.md` as the product dashboard.


## Simplest V5 flow

1. Add your idea:

```bash
make capture-idea IDEA="<your rough product idea>"
```

2. Ask the factory what to do next:

```bash
make next
make skill-route
```

3. Give Codex the suggested prompt from `docs/00-factory-console.md`.

4. Continue one phase at a time. The factory will recommend the driver skill, reviewer skills, blocking gates, and missing evidence.

5. Activate ORBI only for ORBI/Orbisynth products:

```bash
make apply-orbi-profile
```


## External skills first

When you need a new capability, run:

```bash
make skill-discover
```

The factory will point you to existing skill families before suggesting a local custom skill. Install nothing blindly. Audit first, register, then route.

## Session handoff

Before closing a Codex tab or terminal:

```bash
make next
make skill-route
make handoff
```

Open the next session with:

```text
Continue from AGENTS.md, docs/00-factory-console.md, and docs/session-handoff.md.
Do not redo completed work.
```
