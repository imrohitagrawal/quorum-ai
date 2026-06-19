# Generated Enterprise Product

This repository was generated from Codex Product Factory Enterprise Edition.

## Start

```bash
uv sync --all-extras
make validate
make quality
make run
```

Then open:

- Health: `http://127.0.0.1:8000/health`
- Readiness: `http://127.0.0.1:8000/ready`
- OpenAPI UI: `http://127.0.0.1:8000/docs`
- Workspace UI: `http://127.0.0.1:8000/ui`

The workspace UI opens without an API key. Set `OPENROUTER_API_KEY` only if you want live OpenRouter-backed model catalog or execution behavior instead of the default offline-safe fallback path.

## Factory command

Inside Codex:

```text
Run product factory.
```

Do not implement product behavior until the living spec, architecture, security, AI safety, testing, and implementation gates pass.


## Enterprise V4 operating rule

Use `make validate` during generation. Before claiming release readiness, replace all placeholders and run:

```bash
FACTORY_STRICT=1 make validate-strict
```

Open `OPERATING_BLUEPRINT.html` for the step-by-step usage guide.


## V5 guided commands

```bash
make capture-idea IDEA="<your rough product idea>"
make next
make skill-route
make validate
```

Optional ORBI profile for ORBI/Orbisynth-specific products:

```bash
make apply-orbi-profile
```

The factory now recommends one driver skill, reviewer skills, blocking gates, missing evidence, and the next Codex prompt.


## V5.1 study and publishing backbone

This factory now treats learning, publishing, and knowledge-base artifacts as first-class deliverables. Every project can generate:

- Git-backed study modules under `docs/study/`;
- a Confluence page/module tree for each project;
- FAQ/wiki plan;
- technical article plan;
- LinkedIn post/carousel/visual plan;
- visual/media watermark and accessibility rules;
- backend engineering guardrails;
- industry and integration practice review.

Run:

```bash
make publishing-check
make next
```

The factory will still prioritize the MVP and most valued outcome before broad content creation.

## V5.2 External Skills First

This factory searches for existing high-quality skills before creating local custom skills. Use `make skill-discover`, audit candidate skills, register approved skills, then route them as reviewers or local wrappers. Use `make handoff` for multi-session continuity.
