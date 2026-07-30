# ADR Index

Architecture and method decisions. **Records are superseded, never edited** — when
a decision changes, add a new ADR and mark the old one superseded with links both
ways, so the record shows what was believed on a date and what replaced it.

| ADR | Title | Kind | Status |
|---|---|---|---|
| [ADR-0001](adr/0001-initial-architecture.md) | Initial architecture | Architecture | Draft |
| [ADR-0002](adr/0002-sqlite-single-writer-ceiling.md) | SQLite stores stay single-writer (one connection, one lock, no WAL) | Architecture | Accepted — 2026-07-19 |
| [ADR-0003](adr/0003-measure-review-yield-before-setting-a-review-budget.md) | Measure review yield before setting a review budget | Method | Accepted — 2026-07-30 |

**This index was itself stale** until 2026-07-30: ADR-0002 had existed since
2026-07-19 and was never listed here. A hand-maintained index is a derived fact
living in prose, and derived facts in prose rot — see
`docs/analysis/2026-07-30-session-record.md` §6. If it drifts again, generate it
from the directory rather than fixing it by hand a second time.
