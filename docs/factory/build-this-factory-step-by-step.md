# Build This Factory Step by Step

## Step 1 — Create repo

```bash
mkdir codex-product-factory
cd codex-product-factory
git init
```

## Step 2 — Add root instructions

Create `AGENTS.md` from this kit.

## Step 3 — Add skill folders

```bash
mkdir -p .agents/skills
```

For every lifecycle stage, create:

```text
.agents/skills/<skill-name>/SKILL.md
.agents/skills/<skill-name>/checklist.md
```

## Step 4 — Add factory orchestrator

Create `.agents/skills/factory-orchestrator/SKILL.md`.

This is the only skill the user needs to invoke directly.

## Step 5 — Add lifecycle skills

Add:

```text
product-discovery
requirements-engineering
fanatic-critic
architecture-design
ux-design
security-threat-modeling
test-architecture
implementation-planning
vertical-slice-builder
code-quality-review
performance-engineering
sre-observability
release-readiness
post-release-operations
```

## Step 6 — Add policies

Create `policies/` with engineering, security, testing, UX, observability, and release policies.

## Step 7 — Add templates

Create `templates/product/` with generated product skeleton.

## Step 8 — Add validation scripts

Create scripts that fail when required artifacts are missing.

## Step 9 — Add CI templates

Create `.github/workflows/ci.yml` in the product template.

## Step 10 — Add external skill governance

Create `docs/external-skills-governance.md` and `docs/external-skill-installation.md`.

## Step 11 — Test factory

```bash
make bootstrap PRODUCT=../dummy-product
cd ../dummy-product
codex
```

Ask:

```text
Run product factory.
```

Expected behavior:

- Codex reads `PRODUCT_IDEA.md`.
- Codex runs `factory-orchestrator`.
- Codex creates discovery docs first.
- Codex does not write implementation code before gates pass.

## Step 12 — Package as team template

Push to GitHub and mark as template repository.

Your team now starts every product from this factory.
