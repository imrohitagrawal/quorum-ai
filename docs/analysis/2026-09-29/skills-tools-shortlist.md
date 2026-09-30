# Skills and tools shortlist for Quorum's new approach

Date: 2026-09-29. Author: the shortlist subagent.

**Where this comes from.** This shortlist uses only the six lens reports in this folder:
- `agent-skills-and-plugins.md`
- `spec-driven-tooling.md`
- `browser-and-test-agents.md`
- `security-and-review-tools.md`
- `llm-eval-tools.md`
- `vetting-and-risk.md`

**What I checked myself.** I did not re-open any outside source. Every star count, download count, licence and release date below is the lens's own figure, read on 2026-09-29, and I did not measure it again. I ran two commands myself: `ls` of `.agents/skills`, which shows 113 folders, and a check that each in-house skill named in section 3 exists there. `work-package-protocol` is a harness skill and is not in `.agents/skills`. Nothing was installed.

## The answer in five lines

1. **The biggest gains come from tools Quorum already has.** They need to be used against a real, signed-in server, with each acceptance criterion tied to a test that can fail. The tools are Playwright 1.61.1, axe, schemathesis and Hypothesis.
2. **Two free GitHub settings are off: Dependabot and CodeQL.** One would already have flagged a live advisory: `uv.lock` pins `anyio` 4.14.0, which has a CRITICAL TLS advisory (CVE-2026-63374) fixed in 4.14.2. **UNVERIFIED:** whether production runs that version. The Dockerfile ignores `uv.lock`. Running `pip show anyio` in the built image settles it.
3. **Only a few outside items fill a real gap:**
   - Playwright's test **planner** agent. Never its **healer**.
   - An isolated, pinned browser server for exploratory audits, used with the `dogfood` checklist as a method.
   - Coverage of `app.js` from the browser tests.
   - Two workflow and dependency scanners: zizmor and osv-scanner.
   - Trail of Bits reviewer skills.
   - Inspect, for evals of the AI parts.
4. **Most popular "TDD", "testing" and "spec-driven" skill packs repeat rules the repo already has.** They are prose, not checks. Borrow their ideas; do not install them.
5. **Fix the repo's vetting before adopting anything.** The in-house audit script passed three fake malicious skills (vetting lens, section 2.1). Eight of the nine registered external skills have no pinned commit. Six "reviewer-only" skills load as live skills.

---

## 1. Ranked shortlist (12 items)

Stages used below: spec, acceptance tests, build/TDD, verify/review, security, validate/exploratory, accessibility, performance, AI evals, release/post-deploy, orchestration.

### 1. Extend the test tools already installed
- **Stage:** acceptance tests, build/TDD (outer loop), accessibility, security.
- **The gap:** no signed-in browser tests. 22 of 34 browser specs fake the server's replies. Only 11 of 52 acceptance-criterion numbers appear in any test. axe runs with no WCAG 2.2 tags. schemathesis never runs signed in or in multi-step mode.
- **What to do:**
  - Write signed-in, real-server Playwright journeys through the existing fake-Google sign-in seam.
  - Tag each test with its criterion, for example `{ tag: ['@AC-053'] }`. Playwright has supported tags since 1.42, and `e2e/package.json` already requires `^1.42.0`.
  - Add a small script that fails when a criterion's named test does not exist. This is Tessl's `[@test]` link idea.
  - Use `toMatchAriaSnapshot` (Playwright 1.49+) to check the words and structure a user sees.
  - Add the WCAG 2.2 tags to axe.
  - Run schemathesis in multi-step ("stateful") mode, signed in.
  - Add Hypothesis state-machine tests for sessions and limits.
- **Adoption signal:** Playwright 96,863 stars. axe npm 12,366,627 a week. schemathesis PyPI 2,862,441 a month. All read 2026-09-29.
- **Licences:** Playwright Apache-2.0; axe MPL-2.0; schemathesis MIT. Hypothesis's licence is UNVERIFIED (GitHub says NOASSERTION).
- **Security:** nothing new is installed.
- **Overlap:** these are the repo's own tools. The link script replaces the weak check in `scripts/validate_traceability.py`, which accepts any file that contains an AC number.
- **Mode:** install and run in CI (already installed).
- **Evidence strength:** strong for the gap, which the lens measured with grep. The link script is a design; it has not been built or tested.

### 2. Playwright Test Agents: planner, and generator under review. No healer.
- **Stage:** acceptance tests, spec (turns the owner's journey sentences into test plans).
- **Adoption signal:** ships inside `@playwright/test` 1.61.1, already in the lockfile.
- **Licence:** Apache-2.0.
- **Security:**
  - `init-agents --loop=claude` writes three files under `.claude/agents/`, each set to `model: sonnet`, plus a repo-root `.mcp.json`.
  - The planner has an unrestricted code-running tool, `browser_run_code_unsafe`.
  - **The healer's own instructions tell it to fix "assertions and expected values", to "do the most reasonable thing possible to pass the test", and to mark tests `test.fixme()`.** That locks the current behaviour into the tests. This is the failure the review found. Delete the healer file.
- **Overlap:** `webapp-testing`, `e2e-testing-patterns`, `test-architecture`.
- **Mode:** a Claude Code subagent plus a local MCP server, in a throwaway copy first. Keep generated specs out of the owner-approved journey folder until the owner approves them.
- **Evidence strength:** medium. Two lenses read the agent files independently and agree. Nobody ran `init-agents`.

### 3. GitHub Dependabot alerts and security updates, and CodeQL default setup
- **Stage:** security, release.
- **The gap:**
  - Dependabot alerts are off (API 403 "Dependabot alerts are disabled").
  - CodeQL is `not-configured`.
  - CodeQL would be the only security scan of the 10,473-line `app.js`. `make security-scan` does not read `.js` or `.ts` files.
- **Adoption signal:** built into GitHub. There are no stars to read.
- **Cost:** $0 on a public repo.
- **Security:** a settings switch, so no new GitHub App or action gets write access.
- **Setup detail:** the security lens read GitHub's docs table and found that `dependabot.yml` supports `uv`, `npm` and `github-actions`.
- **Overlap:** the prose skill `supply-chain-security`.
- **Mode:** turn on in repo settings (the owner's action), plus a committed `dependabot.yml`.
- **Evidence strength:** strong on the gap. The anyio advisory was found with Trivy and confirmed in the OSV database. Its reach in production is UNVERIFIED.

### 4. Playwright MCP, pinned and isolated. playwright-cli with its skill is the alternative.
- **Stage:** validate/exploratory.
- **Why a separate browser:** the `claude-in-chrome` tool in this harness drives the owner's real Chrome, with real cookies. An exploratory agent needs a throwaway browser instead.
- **Adoption signal:**
  - playwright-mcp: 37,692 stars; npm 7,629,601 a week; v0.0.83 released 2026-09-28.
  - playwright-cli: 13,669 stars; npm 1,152,884 a week.
- **Licence:** Apache-2.0 (Microsoft).
- **Security:**
  - Its own docs say "not a security boundary".
  - The documented install is unpinned: `npx …@latest`. npm shows 34 releases in 60 days.
- **How to run it:**
  - Pin the exact version.
  - Run it `--isolated --headless`, allowed to reach only `http://127.0.0.1:18085`, at project scope.
  - Keep it out of sessions that hold `gh` write access or Fly credentials.
- **Overlap:** `webapp-testing`. The Python `playwright` package is already in the repo.
- **MCP or CLI?** The CLI is Microsoft's claim for fewer tokens; that is UNVERIFIED. Measure both on one audit before choosing.
- **Mode:** MCP server at project scope.

### 5. The `dogfood` and `ce-dogfood` exploratory methods, taken as text only
- **Stage:** validate/exploratory, usability.
- **What they give:**
  - `dogfood` has an issue checklist: dead ends, stale data, unhelpful empty states, unclear errors.
  - `ce-dogfood` gives an order: map the flows, then a scenario matrix, then the browser.
  - `ce-dogfood` also has a rule: a fix counts only when a test fails before it and passes after.
  - Its end states include "Blocked (needs human verify)" and "Blocked (human decision)".
- **Adoption signal:**
  - vercel-labs/agent-browser: 43,350 stars; npm 1,961,492 a week; skills.sh 895,290 installs.
  - EveryInc/compound-engineering-plugin: 25,323 stars.
- **Licences:** Apache-2.0 and MIT.
- **Security:** do not install either.
  - The agent-browser tool has a `postinstall` script and prebuilt binaries, and needs broad shell and network access. The repo policy rejects that combination.
  - Its SKILL.md loads its real instructions from the tool at run time, so reading the file reviews nothing.
  - `ce-dogfood` fixes and commits on its own.
- **Overlap:** none. The review found there is no exploratory charter today.
- **Mode:** reviewer-only method. Copy the text, with attribution, into a repo-owned exploratory charter at pinned commit `8c15ff9f71ae60c7e99e66afe1e2d4b9bf414fe2`.

### 6. Browser coverage of `app.js`, fed into the existing changed-lines coverage gate
- **Stage:** verify/review, build/TDD.
- **The gap:** `app.js` has no coverage and no mutation testing anywhere.
- **What it is:** Playwright's `page.coverage` (Chromium only), then `monocart-coverage-reports` (or `v8-to-istanbul`), then an lcov file. The browser lens confirmed that `diff-cover` 10.3.0 accepts `lcov.info`.
- **Adoption signal:** monocart has only **156 stars**, but npm shows 1,790,044 a week. Treat it as low-credibility maintenance with high use.
- **Licence:** MIT.
- **Security:** a development-only dependency that runs no network calls, as far as the lens read.
- **Overlap:** `mutation-flaky-test-manager` (prose).
- **Mode:** install and run in CI. Make it advisory first. In the same commit, state what makes it blocking.
- **Evidence strength:** weak on fit.
  - The path from served files to source files is UNVERIFIED.
  - The added run time is UNVERIFIED.
  - Coverage works only on Chromium; whether the `mobile` project runs on Chromium is UNVERIFIED.

### 7. zizmor (workflow scanner) and osv-scanner (dependency scanner) in CI
- **Stage:** security, release.
- **The gap:**
  - Only 1 of 54 third-party `uses:` lines is pinned to a commit hash. Movable tags are how the March 2026 attack on the Trivy action spread.
  - `deploy.yml` uses the risky `workflow_run` trigger.
  - `test.yml` has no `permissions:` block.
  - No dependency scan runs in CI, and `npm ci` runs with `--no-audit`.
- **Adoption signal:** zizmor 6,603 stars (MIT); osv-scanner 11,117 stars (Google, Apache-2.0).
- **Security:**
  - Both run offline in CI.
  - Pin both by commit hash. Scanners can be the attack: in March 2026, 76 of 77 `trivy-action` tags were hijacked.
- **Overlap:** `supply-chain-security` (prose).
- **Mode:** install and run in CI.
  - osv-scanner reads `uv.lock` and `package-lock.json` directly. Also run it on the built image.
  - Give it a minimum-count floor, so it cannot pass on an empty input.
- **Evidence strength:** strong on the gaps, which the lens counted. How many alerts each tool would raise is UNVERIFIED.

### 8. trailofbits/skills, as reviewers only
- **Which skills:** `spec-to-code-compliance`, `insecure-defaults`, `differential-review`, `sharp-edges`, `fp-check`, `agentic-actions-auditor`.
- **Stage:**
  - verify/review: `spec-to-code-compliance` sorts each requirement into holds, contradicted, absent, or undocumented. That targets the owner decisions the code does not honour. Example: the 2026-07-23 follow-up decision is built on the server, but `app.js` never sends it.
  - security: the other five.
- **Adoption signal:** 7,289 stars; each skill has 5.9K–7.1K installs on skills.sh.
- **Licence:** CC-BY-SA-4.0. Anything derived must carry the same licence, so install as a plugin and do not copy into the repo.
- **Security:** mostly prose. Scan them before adoption (item 12).
- **Overlap:** `security-threat-modeling`, `owasp-control-mapper`, `code-quality-review`, `traceability-graph-gate` (as a reviewer lens, not a gate).
- **Mode:** Claude Code plugin at project scope, pinned to a commit, auto-update off. Reviewer-only; hand to a separate single writer.
- **Evidence strength:** medium. Two lenses reached this independently. None of the skills was run.

### 9. Anthropic `claude-security` plugin (official marketplace), "scan changes" job
- **Stage:** security, as a threat model and hunt for each feature.
- **What it has:** real code — Python scripts, SARIF output, and finding IDs that stay the same between scans. Separate agents try to disprove each finding before it is reported.
- **Adoption signal:** its host, anthropics/claude-plugins-official, has 37,191 stars. That count is for the whole marketplace, not this plugin.
- **Licence:** "All rights reserved" (agent-skills lens). The security lens marks the terms UNVERIFIED. It can be installed but not copied.
- **Security:**
  - It adds no isolation of its own.
  - It writes a `CLAUDE-SECURITY-*` folder into the repo, so it must not run while another agent is reading the tree (rule 9a).
  - It costs model tokens. The amount was not measured.
- **Overlap:** `security-threat-modeling`, `prompt-injection-defense`, `owasp-control-mapper`.
- **Mode:** Claude Code plugin, run on demand per feature, only after the owner agrees the token cost.

### 10. Inspect (UK AI Security Institute), after a $0 pytest safety-detector corpus
- **Stage:** AI evals.
- **The gap:**
  - The judge's thresholds have never been calibrated against labelled cases with a real model.
  - There is no repeatable live regression run.
  - The medical/legal/financial warning detector is not checked against real questions.
- **Adoption signal:** 2,881 stars; PyPI 2.77M a month; last commit 2026-09-29.
- **Licence:** MIT.
- **Security:**
  - It calls OpenRouter directly, which matches how Quorum already reaches its models.
  - Its built-in fake model (`mockllm`) allows a $0 CI run. The lens confirmed this in the source.
  - Telemetry is UNVERIFIED; no setting was found in the pages read.
- **Overlap:** `llm-evaluation`, a generic template with no method. `tests/evals/` already holds a hermetic golden gate at $0.
- **Mode:**
  - First, a committed pytest corpus of real medical, legal and money questions, plus near-misses that must not warn. No new tool.
  - Then Inspect on demand for judge calibration. It needs the owner's approval and a dry-run cost estimate first; the cost is not estimated.
  - Then the same task with `mockllm` in the advisory nightly job.
  - Needs an ADR, because it reverses the shipped "no eval framework" decision.

### 11. Chrome DevTools MCP
- **Stage:** performance, validate/exploratory (the console, network and memory parts of an audit).
- **Adoption signal:** 52,729 stars; npm 3,138,727 a week; v1.10.1 released 2026-09-23.
- **Licence:** Apache-2.0.
- **Security:**
  - Usage statistics are **on by default**; pass `--no-usage-statistics`.
  - The documented install is unpinned `npx …@latest`; pin it.
  - Same isolation as item 4.
- **Overlap:** `performance-engineering` (prose). The `claude-in-chrome` tool can read the console and network, but in the owner's real browser.
- **Mode:** MCP server at project scope, used in audits only.
- **Evidence strength:** weak on need. No lens showed a performance defect this would have caught. It ranks below the rest for that reason.

### 12. Vetting tools: Claude Code's built-in controls, plus one skill scanner
- **Stage:** orchestration (the adoption gate for items 2, 4, 8, 9 and 11).
- **Built-in controls** (Anthropic, nothing to install):
  - `claude --plugin-dir <dir> plugin details <name>`
  - `disableSkillShellExecution`
  - the MCP allow and deny lists: `allowedMcpServers`, `deniedMcpServers`
  - plugin auto-update off
  - The vetting lens found none of these set today.
- **Scanner — the two lenses disagree:**
  - The agent-skills lens recommends **NVIDIA SkillSpector**: 18,594 stars, Apache-2.0, 71 patterns, SARIF output.
  - The vetting lens recommends **Cisco `skill-scanner`**: 2,564 stars; PyPI 219,709 a month; offline pattern, pipe-tracing and dataflow checks. Its README says Apache-2.0, but GitHub says NOASSERTION.
  - **Neither was run.** Decide with data: run both, in a throwaway copy, on the three fake malicious skills the vetting lens already built. Keep the one that flags case b (all six risk patterns, currently passed with score 70) and case c (payload in a 200 KB+ script). No pattern scanner can catch case a (a plain-English request to leak `~/.ssh`). Only a human or independent-agent read for intent catches it.
- **Overlap:** replaces `scripts/audit_external_skill.py` and the prose skill `external-skill-security-auditor`.
- **Mode:** install and run in a throwaway copy, never in the main tree. A scanner is a second opinion, never the verdict.

### Methods to copy, not install (small, useful)
- **OpenSpec, one change = one spec change.** Every feature PR adds, edits or removes its own criteria in `docs/12` before any code. OpenSpec calls these ADDED / MODIFIED / REMOVED deltas.
- **BMAD Test Architect, three steps:**
  - `atdd`: acceptance tests written first and skipped, then un-skipped one at a time and seen to fail.
  - `test-review`: any critical finding blocks, whatever the score. Example: `expect(true).toBe(true)`.
  - `trace`: waivers need a named human approver, a date, a reason and an expiry.
- **Anthropic `threat-model` skill, "interview" mode** (Apache-2.0): a threat model built with the owner for each feature.
- **Matt Pocock's `grilling` and `to-spec`** (MIT): an interview in rounds for the journey statements, and "use the highest seam possible" for the outer test loop.
- **Anthropic's enterprise skill checklist:** 8 review steps, 3–5 trigger tests, "authors should not be their own reviewers", every update treated as a new deployment.

---

## 2. Considered and rejected

| Item | Reason | Source lens |
|---|---|---|
| GitHub Spec Kit | Duplicates `docs/10-12` and adds a second requirement tree. The heaviest option. Its setup says "commit or stash", which clashes with the no-stash rule. Two outside trials found it slow to review, but each is one person's trial. | spec |
| Kiro | Paid, a separate agent product, and its repo has no licence file. Keep only the idea of checking requirements for contradictions. | spec |
| cc-sdd | Overlaps the repo's subagent and planning flow. One maintainer. | spec |
| BMAD Method + Test Architect (install) | The Test Architect add-on has only 103 stars. The rest of BMAD overlaps most of the 113 skills. Copy its methods instead. | spec |
| Tessl spec-driven-development tile | 55 stars. Beta status and whether an account is needed are UNVERIFIED. Copy the `[@test]` idea only. | spec |
| Task Master | "Commons Clause" licence, its own paid model calls, `npx -y`, no commits for five months. It only breaks down tasks. | spec |
| Pimzino spec-workflow-mcp | GPL-3.0 licence and a dashboard server. | spec |
| OpenSpec (install) | Wants its own `openspec/specs/` folder next to `docs/12`. Trial it on one feature only if the owner asks. | spec |
| playwright-bdd / pytest-bdd | Popular (npm 2.2M and PyPI 3.1M a month), but they add a Gherkin format as a third copy of the criteria. Tagged plain tests do the same job. Use them only if the owner wants to approve `.feature` files. | spec, browser |
| Playwright **healer** agent | Edits assertions until tests pass and skips tests it cannot fix. | agent-skills, browser |
| agent-browser tool (install) | `postinstall` script, binaries, broad shell and network access, instructions fetched at run time. Take the method only. | agent-skills, vetting |
| ce-dogfood (install) | Fixes and commits on its own. Take the method only. | agent-skills |
| browser-use, Stagehand | A paid model call on every step, built for general web tasks. browser-use telemetry sends task text and URLs by default. | browser |
| Pact | Pays off when two sides deploy separately. Quorum is one repo and one deploy. | browser |
| pa11y | Duplicates axe. LGPL-3.0. | browser |
| Lighthouse CI | No release since 2025-06-26. One upload option makes reports public. Cannot measure time-to-answer. | browser |
| nyc | Must rewrite `app.js` before serving it. | browser |
| Stryker (for now) | From its source (not run): mutants switch on through `process.env`, which a browser page lacks, so every mutant would "survive". Every mutant reruns the whole command. Retry only in a throwaway copy. | browser |
| Bandit | Ruff's `S` rules cover it. 8 of 8 inspected hits on `src/` were false alarms. | security |
| gitleaks / trufflehog as a gate | A full-history check of 475 commits gave 20 hits, none real. Adding `.js`/`.ts` to the in-house scan is cheaper. trufflehog is AGPL. | security |
| CodeRabbit, Copilot review, Greptile, PR-Agent | The review plan rules out more standing reviewers. Copilot is paid per review. CodeRabbit leaked an app key in 2025 (search summary only, not opened). Greptile indexes the repo in its cloud. PR-Agent is community-maintained. Codex is already here. | security |
| claude-code-security-review | "Not hardened against prompt injection". Its noise filter drops rate-limit and denial-of-service findings, which is Quorum's money-and-limits defect class. | security |
| `security-guidance` plugin | A paid model call at every stop and every commit. Its end-of-turn review reads a tree other agents are changing. | agent-skills, security |
| `hookify` | Its test rule only looks for the word "pytest" in the session log, which is easy to fake. | agent-skills |
| TDD Guard | Unit-level TDD is already strong here. | agent-skills |
| obra/superpowers | Repeats existing rules, and injects an `<EXTREMELY_IMPORTANT>` block into every session, adding to an instruction load the review already calls too large. | agent-skills |
| addyosmani/agent-skills, wshobson/agents | Prose. The spec skill is already registered. | agent-skills, spec |
| DeepEval | Telemetry on by default. Most metrics need a model judge. Its skill pushes machine-made test data and a paid cloud. | evals |
| Ragas | No commits for seven months. | evals |
| OpenAI Evals | OpenAI API only. | evals |
| Braintrust, LangSmith | Paid hosted services that would receive users' questions. | evals |
| Arize Phoenix | Tracing, not a test gate. Elastic 2.0 licence. | evals |
| autoevals, openevals | Not needed now. They could be a source of judge prompts later. | evals |
| skills.sh install counts as evidence | Can be gamed. One repo shows 310K–450K installs per skill with 496 stars. Use stars, downloads and the maintainer instead. | agent-skills |

**Held back, not rejected** (each needs an owner decision first):
- **Promptfoo:** for attack tests, after the source-fetcher threat model is written. Run it locally with telemetry, update checks and remote attack generation all off. Copy the useful cases into pytest.
- **OWASP ZAP baseline:** against the local simulated server only. Whether its crawler would start paid runs or use up the sign-in limit is UNVERIFIED.
- **Snyk `agent-scan`:** it uploads skill content to Snyk and starts the MCP servers it scans.
- **OpenSSF Scorecard CLI:** measures how well a project is maintained, not whether its content is hostile.
- **`session-report` skill:** a one-off baseline of skill use. Its licence and network use are UNVERIFIED.

---

## 3. In-house skills each item could replace

These are candidates to **archive**, never to delete. Archive only after the replacement has run on real features and shown it works.

A caveat on "prose-only": the agent-skills lens found only 8 of the 113 skills ship any file that is not `.md`, `.txt` or `.json`. I did not open the skills below to confirm each one's contents.

| Recommended item | In-house skill it could replace | Confidence |
|---|---|---|
| 1 (existing tools, extended) + 2 (Playwright planner) + 4 (Playwright MCP) | `webapp-testing`: an external copy that has drifted (202 lines locally, 95 upstream), symlinked in as a live skill. `e2e-testing-patterns`: an external copy with no recorded source (probably wshobson/agents), also symlinked live. | Medium. Both are external, drifted, and outside the registry's controls. |
| 1 (link script) | Nothing to archive. `scripts/validate_traceability.py` gets the check it lacks. `traceability-graph-gate` and `acceptance-criteria-quality-gate` stay but should point at the script. | High that the script is needed. It has not been built. |
| 3 + 7 (Dependabot, CodeQL, zizmor, osv-scanner) | `supply-chain-security` | Medium. Keep it if it holds anything project-specific. |
| 6 (browser coverage) | None. `mutation-flaky-test-manager` stays until JS mutation testing is solved. | — |
| 8 + 9 (Trail of Bits, claude-security) | `security-threat-modeling`, `owasp-control-mapper` (the security lens calls them generic templates that name no tool) | Low to medium. Decide after both run on one feature. |
| 10 (Inspect + safety corpus) | `llm-evaluation` (a generic template with no method) | Medium. |
| 11 (Chrome DevTools MCP) | `performance-engineering` | Low. No measured need yet. |
| 12 (scanner + built-in controls) | `external-skill-security-auditor` (prose), and `scripts/audit_external_skill.py` should be hardened or replaced | High that the script is too weak: it passed all 3 fakes. |
| Methods (dogfood charter, BMAD rules, threat-model interview) | None. These fill gaps no skill covers. | — |

**Separate from replacement: six external skills are registered "reviewer-only" but load as live skills.** They are `codebase-intel`, `deploy-checklist`, `e2e-testing-patterns`, `subagent-driven-development`, `systematic-debugging` and `webapp-testing`, symlinked into the gitignored `.claude/skills`. Either unlink them or set `disable-model-invocation: true`, and record the choice in an ADR.

---

## 4. Phased adoption order, with the vetting step for each

Every phase follows the repo's rules:
- one concern per pull request;
- an ADR for each adoption decision (rule 16d);
- a registry entry with commit SHA, checksum, licence, permissions, reviewer, date and the owner's approval in the owner's own words — marked PROPOSED until the owner gives it;
- a test that can fail for every new gate, with an empty-input floor.

**Phase 0 — fix the vetting before adding anything. $0, no installs.**
- Harden `scripts/audit_external_skill.py`, using fake skills b and c as failing tests:
  - no size skip;
  - flag `allowed-tools`, `!` lines, `hooks.json`, `.mcp.json`, `bin/`, binaries and `postinstall`;
  - any shell, network or secrets hit forces "sandbox or reject".
- Make the onboarding check read the registry. It should fail on an external skill with no SHA; today 8 of 9 would fail.
- Decide on the six live "reviewer-only" symlinks (section 3).
- Register the enabled user-level plugins (`codex`, `frontend-design`, `ui-ux-pro-max`). Decide whether official-marketplace auto-update stays on.
- **Vetting step:** normal repo review. These are repo changes, not adoptions.

**Phase 1 — free security settings and offline CI scanners.**
- Run `pip show anyio` in the built image first, to settle whether production is affected.
- Owner turns on Dependabot alerts, Dependabot security updates and CodeQL default setup. Commit `dependabot.yml`.
- Add zizmor and osv-scanner, pinned by commit hash. Make them advisory with a count floor, and state in the same commit what makes them blocking.
- **Vetting step:** confirm each action's pin and publisher. Prove each scanner goes red on a seeded bad input and refuses to pass on an empty input. Read the first CI log for the number it counted.

**Phase 2 — acceptance tests on the tools already installed (item 1), then the planner (item 2).**
- Write one signed-in, real-server starting test. Add `@AC-NNN` tags and the link script. Carry one feature through the double loop.
- Add the WCAG 2.2 axe tags. Add schemathesis stateful mode, signed in.
- Then run `npx playwright init-agents --loop=claude` in a `git archive` copy.
- **Vetting step for the planner:**
  - read the `.mcp.json` and `.claude/agents` it writes as a diff;
  - delete the healer;
  - restrict `browser_run_code_unsafe` if possible;
  - confirm the owner can read the plan;
  - confirm the generated test fails on the known History defect before any fix.

**Phase 3 — exploratory audits (items 4, 5, 11).**
- Copy the dogfood and ce-dogfood method text, with attribution, into a repo-owned exploratory charter. The dogfood text is pinned at commit `8c15ff9`.
- Add Playwright MCP (or the CLI) and Chrome DevTools MCP at project scope, exact version, `--isolated --headless`, allowed only `127.0.0.1:18085`, and `--no-usage-statistics` for DevTools.
- **Vetting step:**
  - read every file in the pinned package;
  - run in a sandbox copy with no `gh`, Fly, OpenRouter or Google credentials, and watch outbound connections;
  - run 3–5 trigger tests, and check it does not take triggers from `webapp-testing` or `e2e-testing-patterns`;
  - never point it at production with a real account.

**Phase 4 — `app.js` browser coverage (item 6).**
- Make it advisory first. Measure the added run time and the path mapping.
- **Vetting step:** remove a covered line from a test and check the changed-lines coverage number moves. Monocart's low star count means pinning it and reviewing each version bump.

**Phase 5 — security reviewers (items 8, 9) and a scanner (item 12).**
- Run SkillSpector and Cisco `skill-scanner` in a throwaway copy on the three fake skills. Keep the better one.
- Scan the Trail of Bits skills and `claude-security` with it, and have an independent agent (for example Codex) read them for intent.
- Install them as project-scope plugins, pinned, auto-update off, reviewer-only.
- `claude-security` needs the owner to agree the token cost, and must not run while another agent is reading the tree.
- **Vetting step:** `claude --plugin-dir <clone> plugin details <name>`, the enterprise 8-step read, and a scan result recorded in the registry.

**Phase 6 — AI evals (item 10).**
- First, the pytest safety-detector corpus. $0, blocking.
- Then Inspect with `mockllm` in the nightly job.
- Then one on-demand live calibration run with the owner's approval and a dry-run cost estimate. It needs an ADR.
- Promptfoo attack tests only after the source-fetcher threat model exists.
- **Vetting step:** confirm Inspect's telemetry behaviour, which is UNVERIFIED, by watching outbound connections in a sandbox run with the fake model.

---

## 5. Where the evidence is weak

- **No tool in this shortlist was run by any lens.** Every behaviour comes from the maintainers' own docs and source. The one exception: Trivy, gitleaks and ruff were run for the security findings.
- **Adoption numbers are the lenses' own readings from 2026-09-29.** I did not re-measure them. Stars and downloads measure use, not quality. npm counts include CI and bots.
- **The lenses disagree on two points:**
  - which skill scanner to use (SkillSpector or Cisco);
  - whether Playwright MCP adds anything over tools already present. The browser lens says adopt; the vetting lens says it overlaps. I chose adopt-isolated, because the existing `claude-in-chrome` tool uses the owner's real session.
- **Nothing measured shows any of these items reduces the user-journey defects the owner keeps finding.** Items 1 and 5 are ranked highest because they target those defects directly, not because a trial proved them.
- **The anyio advisory's reach in production is UNVERIFIED.**
- **A pattern in the vetting report tripped a harness check.** The vetting lens report contained the text `--dangerously-skip-permissions`, and a harness check flagged it. The text is a quotation from the `nx` npm attack write-up, not an instruction. Nothing was acted on.
