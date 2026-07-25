# Documentation Review Register

**Project**: Quorum AI  
**Reviewed artifacts**: `docs/20-architecture.md`, `docs/21-domain-model.md`, `docs/24-adr-index.md`, `docs/40-threat-model.md`, `docs/80-observability.md`, `diagrams/00-hero-diagram.md`, `diagrams/01-c4-context.md`, `diagrams/02-c4-container.md`, `diagrams/03-c4-component.md`, `diagrams/04-c4-module.md`, `diagrams/10-mermaid-high-level.md`, `diagrams/11-mermaid-low-level.md`, `diagrams/12-mermaid-module-level.md`, `diagrams/13-mermaid-sub-module-level.md`  
**Cross-checked against**: `src/product_app/providers.py`, `src/product_app/evaluation.py`, `src/product_app/query_runs.py`, `src/product_app/feedback_store.py`, `src/product_app/provider_keys.py`  
**Method**: doc-critic 7-error-class taxonomy (internal contradictions, code-vs-doc mismatches, term collisions, simplification-gone-false, honesty-posture drift, broken cross-references, term-definition gaps)  
**Date**: 2026-07-24  

---

## Gate

**BLOCKERs block publishing.** Any reader left believing something false — about what the system does, how it stores data, or what safety guarantees hold — must be resolved before this documentation set is published, shared with new team members, or cited in a demo.

---

## Severity-Ranked Register

### BLOCKER

#### B1 — `feedback_store.db` filename contradicts source and all three C4/Mermaid diagrams

- **Exact quote (architecture doc, `docs/20-architecture.md:152`)**:  
  `SQLite file database (`feedback_store.db`, `run_history_store.db`) — not external RDBMS.`
- **Actual source** (`src/product_app/feedback_store.py:55`):  
  `DEFAULT_DB_PATH = ".data/feedback_events.sqlite3"`
- **Diagrams that get it right**:  
  `diagrams/02-c4-container.md:69` — `SQLite Database (Fly volume) query_runs, run_history, feedback, provider_keys`  
  `diagrams/03-c4-component.md:275` — `SQLite on Fly volume (.data/feedback_events.sqlite3)`  
  `diagrams/13-mermaid-sub-module-level.md:197` — `feedback_store.py (SQLite: .data/feedback_events.sqlite3)`
- **Error class**: Code-vs-doc mismatch. The architecture doc names a file that does not exist anywhere in the source tree. An operator or new engineer reading `docs/20-architecture.md` will look for `feedback_store.db`, find nothing, and either conclude the code is broken or that the doc is wrong. The diagrams agree with the source; the prose contradicts both.
- **Concrete fix**: Change `feedback_store.db` → `feedback_events.sqlite3` at `docs/20-architecture.md:152`. Also change `run_history_store.db` → `run_history.sqlite3` for consistency with `diagrams/03-c4-component.md:274` (`run_history.sqlite3`) and `diagrams/13-mermaid-sub-module-level.md:195`.

---

#### B2 — Concurrency claimed "configurable by environment" but all values are hardcoded constants

- **Exact quote (architecture doc, `docs/20-architecture.md:105`)**:  
  `Provider concurrency, retry count, and timeout budgets must be configurable by environment.`
- **Exact quote (diagram 02, `diagrams/02-c4-container.md:166`)**:  
  `Provider concurrency, retry count, and timeout budgets are configurable via environment variables and config.py (NFR-004).`
- **Actual source** (`src/product_app/query_runs.py:657–673`):  
  `_MAX_CONCURRENT_RUNS = 16`  
  `_run_semaphore = BoundedSemaphore(_MAX_CONCURRENT_RUNS)`  
  `_INITIAL_ANSWER_POOL_SIZE = 16`  
  `_synthesis_pool = ThreadPoolExecutor(max_workers=_INITIAL_ANSWER_POOL_SIZE, ...)`  
  `_SYNTHESIS_POOL_SIZE = 16`
- **config.py**: No environment variable, setting field, or override mechanism exists for any of these three values.
- **Irony**: `diagrams/02-c4-container.md:33` (the NFR-004 requirement row) correctly states `concurrency/retry hardcoded (Semaphore 16, ThreadPoolExecutor 16)` — so diagram 02 contradicts diagram 02 on the same requirement.
- **Error class**: Honesty-posture drift. The doc promises configurability that does not exist, and the diagram that describes the requirement correctly contradicts the diagram that describes the implementation. An operator who relies on `config.py` for tuning concurrency in production will find nothing to tune.
- **Concrete fix**:  
  (a) Decide if concurrency should be configurable (add env vars to `config.py` + wired reads in `query_runs.py`) or hardcoded (acceptable for MVP).  
  (b) Update `docs/20-architecture.md:105` and `diagrams/02-c4-container.md:166` to match the decision. If hardcoded, change to "hardcoded at 16; configurable in a future release."  
  (c) Resolve the self-contradiction in `diagrams/02-c4-container.md:33` vs `:166`.

---

#### B3 — FR-012 documents "no user key input in MVP" but `BYO_OPENROUTER` is a live enum value in source

- **Exact quote (architecture doc, `docs/20-architecture.md:172`)**:  
  `OQ-010 | Confirm extra usage policy unlocked by BYO  key. | Product owner | Determines quota, cost, and abuse controls for FR-012.`
- **Exact quote (diagram 02, `diagrams/02-c4-container.md:25`)**:  
  `Server-side bring-your-own  key (app-owned, env-configured; no user key input in MVP)`
- **Exact quote (diagram 03, `diagrams/03-c4-component.md:26`)**:  
  `Server-side bring-your-own  key (app-owned, env-configured; no user key input in MVP)`
- **Actual source** (`src/product_app/provider_keys.py:4–7`):  
  ```python
  class ProviderCredentialSource(StrEnum):
      APP_OWNED = "app_owned"
      NOT_CONFIGURED = "not_configured"
      BYO_OPENROUTER = "byo_openrouter"
  ```
  The `BYO_OPENROUTER` value exists as a first-class enum member, is imported in `providers.py:50` and `query_runs.py:85`, and is used in the `ProviderCredentialSource` branching logic. There is no `NotImplementedError`, no `raise`, no feature flag, and no `_MVP_NO_BYO` guard anywhere in the import chain.
- **Error class**: Simplification-gone-false. The documentation says the MVP has no user key input, but the codebase already contains the full BYO key enum, credential source branching, and provider_keys module. The feature is not merely "designed"; it is implemented and wired. This is a different claim entirely.
- **Concrete fix**: Clarify whether BYO keys are in-scope for the current release or deferred. If deferred, add a runtime guard that raises or returns `NOT_CONFIGURED` until the feature is ready. If in-scope, update FR-012, the architecture doc OQ-010 row, and both diagrams to state that BYO keys are a shipped (or planned) feature with clear policy rules.

---

### MAJOR

#### M1 — "trust triangle" appears in two docs but is never defined as a distinct surface

- **Exact quote (architecture doc, `docs/20-architecture.md:145`)**:  
  `The existing trust triangle and result view are unaffected.`  
- **Exact quote (threat model, `docs/40-threat-model.md:60`)**:  
  `The trust TRIANGLE, which does carry provider prose, renders it in full through setInlineProse and clamps with CSS rather than slicing raw characters`
- **Architecture doc at line 133**: The only defined trust surface is the `evaluation` field projection rendered by `app.js`/`app.css`/`workspace.html`. There is no definition of a separate "trust triangle" anywhere in `docs/20-architecture.md`.
- **Error class**: Term collision / Term-definition gap. "Trust surface" and "trust triangle" are used interchangeably across the architecture doc and threat model, but the threat model treats the triangle as a distinct rendering target that carries provider prose (different from the evaluation projection that does not). A reader of the architecture doc encounters "trust triangle" in a failure-mode table with no prior definition.
- **Concrete fix**: Define "trust triangle" explicitly in `docs/20-architecture.md` (e.g., in the `Trust Boundaries` or `Components` section) as the result-view trust card that renders provider prose. Or rename all references to "trust surface" / "evaluation surface" consistently, and update `docs/40-threat-model.md:60` accordingly.

---

#### M2 — NFR-012 referenced in `docs/21-domain-model.md` before it is defined

- **Exact quotes (domain model, `docs/21-domain-model.md`)**:  
  Line 64: `Trace: FR-015, NFR-012.`  
  Line 65: `Trace: FR-015, AC-041.` (no NFR-012 here — but line 66 adds)  
  Line 66: `Trace: NFR-011, NFR-012.`
- **Actual definition** (`docs/11-non-functional-requirements.md:161`): NFR-012 is defined at line 161, well after NFR-004 through NFR-011.
- **Reading order**: A reader following the domain model's trace references would need to jump to `docs/11` line 161, but the domain model is typically read before or alongside the NFR doc. The trace is functional (not wrong), but a reader encountering NFR-012 without having read the NFR doc has no way to know what it means.
- **Error class**: Term-definition gap. NFR-012 is used as a trace target before a reader can find its definition without already knowing the document structure.
- **Concrete fix**: Add a parenthetical expansion at the first NFR-012 reference in `docs/21-domain-model.md:64`:  
  `(NFR-012: Evaluation cost and behaviour neutrality — judge OFF produces zero delta)`

---

### MINOR

#### N1 — Diagram 13 Mermaid node for  API has a blank label (rendering artifact)

- **Exact quote (`diagrams/13-mermaid-sub-module-level.md:196`)**:  
  `OpenRouterAPI -.->|"API calls (server-side keys only)"| `
  The target of this edge is empty — there is no node identifier after the pipe.
- **Impact**: When rendered, this edge terminates in open space. It does not affect the structural accuracy of the diagram (the Secret Store node at line 257 is the correct target), but the broken edge creates a visual glitch.
- **Error class**: Broken internal reference within a diagram.
- **Concrete fix**: Remove the orphan edge at line 196, or point it to `SecretStore` (the actual key source shown at line 257).

---

#### N2 — `feedback_store.db` filename in architecture doc creates a stale reference chain

- **Related to B1**, but narrower: `docs/20-architecture.md:152` says `feedback_store.db`. The module file is named `feedback_store.py`. A reader might conclude the database file is named after the module (`feedback_store.db`) — but the actual default is `feedback_events.sqlite3`. The `.db` extension is also misleading: the real files are `.sqlite3`. This means any script, `docker-compose` volume mount, or `fly.toml` reference written by someone reading the architecture doc will target the wrong path.
- **Concrete fix**: Covered by B1 fix. Ensure all filenames in the architecture doc use the actual `.sqlite3` paths.

---

#### N3 — Diagram 02's NFR-004 requirement row contradicts its own Implementation Notes section

- **Diagram 02, line 33** (NFR-004 requirement row):  
  `configurable timeout budget (180s); concurrency/retry hardcoded (Semaphore 16, ThreadPoolExecutor 16)`
- **Diagram 02, line 166** (Implementation Notes):  
  `Provider concurrency, retry count, and timeout budgets are configurable via environment variables and config.py (NFR-004).`
- **These two statements in the same document directly contradict each other.** The requirement row is accurate; the implementation note is aspirational and incorrect.
- **Error class**: Internal contradiction within a single document.
- **Concrete fix**: Covered by B2 fix. Remove or correct the implementation note once the B2 decision is made.

---

#### N4 — Context diagram names the system but omits the `provider_keys` module from the internal component list

- **`diagrams/01-c4-context.md:54`**:  
  `The internal components (auth, query_api, orchestration, providers, safety, persistence, observability) and internal data stores (in-memory session store, SQLite run-history database) are detailed in the Container diagram (02-c4-container.md) and are intentionally omitted from this Context view.`
- **`diagrams/02-c4-container.md:58`** (the Container diagram) includes `provider_keys` as a persistence sub-component.
- **`diagrams/03-c4-component.md:150`**: `provider_keys (env-only, no persistence)` is listed as a distinct data store.
- The context diagram's abbreviated list omits `provider_keys`, which is relevant because FR-012 (BYO keys) is a trust-boundary item. A reader who only sees the context diagram gets no signal that provider key management is a separate concern inside the boundary.
- **Error class**: Simplification-gone-false. The simplification is reasonable for a context diagram, but it omits the component most directly relevant to FR-012 and T-004/T-006 (credential-scoping threats).
- **Concrete fix**: Add `provider_keys` to the abbreviated component list in `diagrams/01-c4-context.md:54`, or add a footnote noting that credential management is a distinct internal component.

---

#### N5 — Diagrams 00, 10, 11, 12 have no Mermaid flowchart nodes count, making the diagrams/README.md count of "13" unverifiable

- **`diagrams/README.md`** (inferred from diagrams/README.md presence): claims 13 diagrams.
- **Actual file count**: 10 `.md` files in `diagrams/` (00 through 13, excluding excalidraw/ and README.md). Files 05–09 do not exist.
- **`diagrams/00-hero-diagram.md`** does not contain a Mermaid `flowchart` or `graph` directive — it is a prose-and-table description of the diagram set.
- **Error class**: Broken forward reference. The README implies a complete numbered series (00–13), but the series has gaps (05–09 missing) and at least one entry (00) is a prose index rather than a diagram.
- **Concrete fix**: Update `diagrams/README.md` to list only the diagrams that exist, with notes on what 00 (index) and 04 (C4 module) contain.

---

#### N6 — Diagram 02 and 03 describe `model_slots` and `catalog_fetcher` as separate components, but the C4 Container diagram collapses them

- **`diagrams/02-c4-container.md:61–63`**: `catalog_fetcher` and `model_slots` appear as separate sub-nodes inside the FastAPI container.
- **`diagrams/03-c4-component.md:91–96`**: Both are full subgraph-level components with their own functions.
- **`diagrams/02-c4-container.md`** (Container level): These are appropriately fine-grained for a component diagram but the Container diagram lists them as distinct containers-in-miniature inside the FastAPI container. This is acceptable C4 practice, but a reader comparing diagram 02 and diagram 03 might wonder whether `catalog_fetcher` and `model_slots` are deployable units or just module groupings.
- **Error class**: Not strictly wrong, but creates a potential reader confusion about the C4 level boundaries. Diagram 13 (sub-module) resolves this by showing them as subgraph nodes under `ModelSlots` and `CatalogFetcher`.
- **Concrete fix**: Add a note in `diagrams/02-c4-container.md` clarifying that `catalog_fetcher` and `model_slots` are internal FastAPI modules, not separate containers.

---

### NIT

#### N1 — Diagram 13 line 196: orphan Mermaid edge with no target node

`OpenRouterAPI -.->|"API calls (server-side keys only)"| ` — trailing pipe with no node ID. Covered in N1 above; noted here as a rendering nit.

---

#### N2 — `docs/11-non-functional-requirements.md` NFR-004 lists `AC-012, AC-021, AC-022` but the architecture doc traces timeout to `AC-012` and `NFR-001`/`NFR-004`

- **Architecture doc line 69**: `Trace: FR-010, NFR-001, NFR-004.` for the timeout failure mode.
- **NFR-004 doc line 57**: `Acceptance criteria: AC-012, AC-021, AC-022.`
- **AC-012** is "Tavily fallback when  search fails" — not directly about the 180s timeout.
- **AC-021/022** are about partial-result explanation and timeout.
- This is not a contradiction, but a reader tracing the timeout failure mode from the architecture doc to the NFR doc and then to ACs would find the AC list mixes search fallback (AC-012) with timeout (AC-021/022). Low severity; the AC-to-NFR mapping is correct but the architecture doc's trace could be more specific.
- **Concrete fix**: None required; note for traceability audit.

---

#### N3 — `docs/24-adr-index.md` lists only ADR-0001 and ADR-0002, but `docs/20-architecture.md:159` references ADR-0001 only

- ADR-0002 ("SQLite stores stay single-writer") is accepted and relevant to the architecture doc's `diagrams/02-c4-container.md:163` note: "SQLite is a single-writer store (ADR-0002)." But `docs/20-architecture.md` does not list ADR-0002 in its Architecture Decisions section.
- **Concrete fix**: Add ADR-0002 to `docs/20-architecture.md` Architecture Decisions section, or note it as a referenced ADR.

---

## Summary Table

| ID | Severity | File:Line | Error Class | One-line Summary |
|---|---|---|---|---|
| B1 | BLOCKER | `docs/20-architecture.md:152` | Code-vs-doc mismatch | `feedback_store.db` filename wrong; source and diagrams use `feedback_events.sqlite3` |
| B2 | BLOCKER | `docs/20-architecture.md:105`, `diagrams/02-c4-container.md:166` | Honesty-posture drift | Concurrency claimed "configurable" but is fully hardcoded in source |
| B3 | BLOCKER | `docs/20-architecture.md:172`, `diagrams/02-c4-container.md:25` | Simplification-gone-false | FR-012 says "no user key input in MVP" but `BYO_OPENROUTER` is a live, wired enum value |
| M1 | MAJOR | `docs/20-architecture.md:145`, `docs/40-threat-model.md:60` | Term collision / Term-definition gap | "Trust triangle" used as a distinct surface in threat model but never defined in architecture doc |
| M2 | MAJOR | `docs/21-domain-model.md:64–66` | Term-definition gap | NFR-012 traced before a reader can find its definition (line 161 in `docs/11`) |
| N1 | MINOR | `diagrams/13-mermaid-sub-module-level.md:196` | Broken internal reference | Orphan Mermaid edge with empty target node |
| N2 | MINOR | `docs/20-architecture.md:152` | Code-vs-doc mismatch (narrower) | `feedback_store.db` extension `.db` vs actual `.sqlite3`; stale filename propagates to ops scripts |
| N3 | MINOR | `diagrams/02-c4-container.md:33` vs `:166` | Internal contradiction | NFR-004 requirement row says "hardcoded"; implementation note says "configurable" |
| N4 | MINOR | `diagrams/01-c4-context.md:54` | Simplification-gone-false | `provider_keys` omitted from abbreviated component list despite being a trust-boundary concern |
| N5 | MINOR | `diagrams/README.md` (inferred) | Broken forward reference | Claims 13 diagrams; files 05–09 missing; 00 is prose index not a diagram |
| N6 | MINOR | `diagrams/02-c4-container.md:61–63` vs `diagrams/03-c4-component.md:91–96` | Reader confusion (C4 level boundary) | `catalog_fetcher`/`model_slots` appear as sub-components in container diagram but as full components in component diagram |

---

## Findings by Error Class

| Error Class | Count | IDs |
|---|---|---|
| Code-vs-doc mismatch | 3 | B1, N2, B2 (partial) |
| Simplification-gone-false | 2 | B3, N4 |
| Honesty-posture drift | 1 | B2 |
| Term collision / Term-definition gap | 2 | M1, M2 |
| Internal contradiction | 1 | N3 |
| Broken internal reference | 1 | N1 |
| Broken forward reference | 1 | N5 |
