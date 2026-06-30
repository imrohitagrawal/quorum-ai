---
name: codebase-intel
description: Unified codebase intelligence. Handles all questions about structure, logic, risk, and dependencies. Combines natural-language Q&A with deterministic lookups and pre-edit blast radius checks.
permissions:
  allow:
    - Bash(wednesday-skills query *)
    - Bash(wednesday-skills blast *)
    - Bash(wednesday-skills fill-gaps *)
    - Read(.wednesday/codebase/MASTER.md)
    - Bash(git log *)
    - Bash(git diff *)
---

# Codebase Intelligence Specialist

This skill provides a comprehensive understanding of the project's structure, intent, and risk. Use it for everything from high-level architecture questions to detailed impact analysis before editing code.

## When to use

### 1. Codebase Discovery & Q&A
- "What does `tokenService` do?" (Summaries)
- "Where is the payment logic located?" (Role/Path mapping)
- "Show me an overview of the architecture." (Stats & Entry points)
- "Who last touched this file?" (Git history)
- "Find circular dependencies or dead code." (Structural audit)

### 2. Risk Assessment (Before Editing)
- "Is it safe to change this function signature?"
- "What is the blast radius of this file?"
- "What will break if I delete this constant?"

### 3. Graph Maintenance
- If a query returns "not mapped" or coverage is low.
- If you notice missing dependencies in the graph.

## When not to use

- **Pure code implementation**: When the user asks you to write new code, use the coding skill instead
- **Debugging runtime issues**: When the issue requires running the application or reading logs, use debugging tools
- **Non-codebase questions**: General programming questions that don't involve this specific codebase
- **Real-time data**: This skill provides static analysis; runtime metrics need monitoring tools
- **Direct file editing**: When the user explicitly asks to modify files, use the coding skill with blast radius checks

---

## How to use — by task type

### 🔍 Discovery & Q&A
1. **File Summary**: `Bash(wednesday-skills query getFileSummary <file_path>)`
   - Returns: Role, Summary, Risk Score, and Blast Radius.
2. **Architecture Stats**: `Bash(wednesday-skills query getCodebaseStats)`
   - Use `getHighConfidenceEntryPoints` to identify the best starting files.
3. **Advanced Lookups**:
   - `Bash(wednesday-skills query getHighRiskFiles 70)` — find critical technical debt.
   - `Bash(wednesday-skills query getCircularDependencies)` — find architectural smells.
   - `Bash(wednesday-skills query getAllDeadCode)` — find unreachable modules.
4. **Context**: `Read .wednesday/codebase/MASTER.md` for danger zones and primary data flows.
5. **History**: `Bash(git log --follow --oneline -20 -- <file>)` for authorship.

### ⚠️ Pre-Edit Safety Check (Mandatory)
Before modifying any file, you MUST perform these checks:
1. **Check Risk**: `Bash(wednesday-skills query getFileSummary <file_path>)`
   - **Score 0–30**: Proceed directly.
   - **Score 31–60**: Inform dev of the risk, proceed with care.
   - **Score 61–80**: List direct dependents and transitive count; ask confirmation.
   - **Score 81–100**: **STOP**. Require explicit dev approval before touching.
2. **Blast Radius**: `Bash(wednesday-skills blast <file_path>::<symbol_optional>)`
   - Review direct/transitive callers. Use this for cross-language impact (Go/Py/JS).

### 🛠 Graph Maintenance & Gaps
If you hit "not mapped" or detect a missing link:
1. **Gap Check**: `Bash(sqlite3 .wednesday/graph.db "SELECT file_path, meta FROM nodes WHERE file_path LIKE '%<file>%'")`
   - Check `meta` for `gaps.eventEmitter`, `gaps.dynamic`, etc.
2. **Fill Gaps**: `Bash(wednesday-skills fill-gaps --file <file> --min-risk 50)`
   - *Rule*: Only edges with confidence > 0.70 are added automatically.
3. **Annotations**: If gaps persist, ask dev to add `// @wednesday-skills:connects-to <symbol> → <file>`.
4. **Refresh**: `Bash(wednesday-skills analyze --incremental)` after adding annotations.

---

## 🚫 Never
- **Guess**: If data is missing, report "Not mapped" and suggest `wednesday-skills map --full`.
- **Skip Checks**: Never edit a file with risk > 80 without explicit dev confirmation.
- **Token Bloat**: Do NOT read raw source files to answer structural questions.
- **Add Unreliable Edges**: Never manually add edges with confidence below 0.70.

## Inputs

- **File path or symbol name** (required): The target for investigation
- **Optional context**: Previous conversation or explicit question phrasing
- **Optional scope**: `risk`, `summary`, `dependencies`, `history`

## Owned outputs

- **Codebase summaries**: Role, purpose, and risk assessment
- **Dependency graphs**: Direct and transitive callers/callees
- **Architecture insights**: Entry points, danger zones, data flows
- **Git context**: Authorship, recent changes, blame

## Allowed tools

- `Bash(wednesday-skills query *)` — Query the codebase graph
- `Bash(wednesday-skills blast *)` — Blast radius analysis
- `Bash(wednesday-skills fill-gaps *)` — Graph maintenance
- `Read(.wednesday/codebase/MASTER.md)` — Architectural context
- `Bash(git log *)` — Git history
- `Bash(git diff *)` — Uncommitted changes
- `Glob` — File discovery
- `Grep` — Pattern search
- `Read` — File content (only when graph data unavailable)

## Forbidden actions

- **Raw file reads for structural questions**: Use graph queries instead
- **Editing code without blast radius check**: Always run risk assessment first
- **Adding low-confidence edges**: Never add edges below 0.70 confidence
- **Assuming unverified dependencies**: Report "Not mapped" if graph lacks data

## Procedure

1. **Receive query** → Identify intent (Q&A, risk, graph maintenance)
2. **Route to appropriate tool**:
   - Q&A → `wednesday-skills query getFileSummary`
   - Risk → `wednesday-skills query getHighRiskFiles`
   - Dependencies → `wednesday-skills blast <file>`
3. **Execute with blast radius check** if editing is anticipated
4. **Synthesize response** with source citations
5. **Flag gaps** if graph data is incomplete

## Quality bar

- **Accuracy**: All file paths and symbols must be verified against actual code
- **Completeness**: Risk scores must include blast radius context
- **Actionability**: Each response must include concrete next steps
- **Transparency**: "Not mapped" must be reported when graph data is missing

## Validation

- Query results are cross-referenced with `git log` for recent changes
- Risk scores are validated against dependency graph depth
- Anti-patterns: Never guess at architecture without graph evidence

## Handoff contract

- **To Coding**: Provide risk score (0-100), blast radius list, and specific files requiring review
- **To Testing**: Identify which files have high coupling and need test coverage
- **To Architecture**: Flag circular dependencies and architectural smells

## Stop conditions

- Query returns complete data with high confidence (>0.90)
- User explicitly asks to stop investigation
- Graph query times out (fail gracefully with "Not mapped")
- Risk score exceeds 80 without user confirmation

## Examples

### Example 1: File Summary
**Query**: "What does `auth.py` do?"
**Response**: "auth.py handles session management and CSRF protection. Risk score: 35/100. Used by 12 files. Primary callers: main.py, middleware.py."

### Example 2: Pre-edit Safety Check
**Query**: "Can I safely rename `getUser` to `fetchUser`?"
**Response**: "Risk: 72/100. 8 direct callers, 23 transitive. Recommend: (1) Check each caller, (2) Add deprecation wrapper, (3) Update tests first."

### Example 3: Dependency Audit
**Query**: "Show me circular dependencies"
**Response**: "Found 2 cycles: auth.py ↔ session.py, db.py ↔ cache.py. Recommend: break auth→session first as it has lowest coupling."

## Anti-examples

### Anti-example 1: Unverified Assumption
**Bad**: "The payment module probably handles refunds."
**Good**: "payment.py has no refund handling. `refund.py` contains `processRefund()` called by `order.py:handleCancellation()`."

### Anti-example 2: Skipping Blast Radius
**Bad**: "I'll just rename this utility function."
**Good**: "Renaming `formatDate()` (risk: 68) affects 15 files. Blast radius: templates (8), api (5), tests (2). Recommend staged rename with alias."

### Anti-example 3: Low-confidence Edge
**Bad**: "I'll add this edge with 0.55 confidence since it looks right."
**Good**: "Confidence 0.55 is below threshold (0.70). Annotate with `// @wednesday-skills:connects-to` and run full analysis."

## 📄 Source Citation
Always end with the source:
- `graph.db` — Structural/Summary data
- `MASTER.md` — Architectural context
- `git log` — History/Authorship
