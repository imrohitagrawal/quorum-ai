# Vendored third-party assets

These files are served same-origin under `/static/vendor/` so the app's strict
Content-Security-Policy never has to allow a third-party CDN.

Two unrelated things live here: the **Markdown parser** the workspace renders
provider text with, and the **interactive API docs** (Swagger UI).

## `markdown-it` — the workspace Markdown parser

`markdown-it` 14.1.1 (MIT) replaced a hand-written renderer, for the reasons and
measurements in
`docs/adr/0014-vendor-a-markdown-parser-instead-of-hand-rolling-one.md`.
`src/product_app/templates/workspace.html` loads it immediately before `app.js`
(both `defer`, which preserves document order), and `app.js` configures it with
`html: false` plus eight deliberate deviations — recorded, with what each one
prevents, in
`docs/adr/0015-how-the-vendored-markdown-parser-is-configured.md`.

The `dist` UMD build is self-contained: `grep -c "require(" markdown-it.min.js`
prints `0`, so there is no module resolution and no build step.

**`html: false` is the entire XSS posture.** It is not pinned by this file — it
is pinned by `e2e/tests/invariants/markdown-corpus.spec.ts`, which feeds a live
`<script>` through a provider answer and asserts the rendered DOM contains no
script element. Setting `html: true` turns that test red.

## Swagger UI — the interactive API docs

FastAPI's built-in `/docs` loads Swagger UI from `cdn.jsdelivr.net` (and a
favicon from `fastapi.tiangolo.com`), which the CSP blocks — so the stock docs
render blank. `main._register_docs_routes` serves a custom `/docs` that points
at the copies here instead.

Only **Swagger UI** is self-hosted. ReDoc was intentionally NOT vendored: it
cannot be served CSP-clean without widening the policy (it builds its search
index in a `blob:` Worker that `script-src 'self'` blocks on standards-compliant
browsers, and it fetches an external `cdn.redoc.ly` logo that `img-src` blocks).
Swagger UI is a functional superset — it renders the whole schema plus
interactive requests — and stays fully within the strict CSP.

## Provenance (pinned)

| File | Upstream | Version | Licence |
|---|---|---|---|
| `markdown-it.min.js`   | `markdown-it` (npm, via cdn.jsdelivr.net)     | 14.1.1 | MIT |
| `swagger-ui-bundle.js` | `swagger-ui-dist` (npm, via cdn.jsdelivr.net) | 5.18.2 | Apache-2.0 |
| `swagger-ui.css`       | `swagger-ui-dist` (npm, via cdn.jsdelivr.net) | 5.18.2 | Apache-2.0 |
| `favicon-32x32.png`    | `swagger-ui-dist` (npm, via cdn.jsdelivr.net) | 5.18.2 | Apache-2.0 |

## SHA-256 checksums

These were prose until 2026-08-05: four hashes that **nothing compared against
the files**, so any one of them could have been stale, or the file swapped, for
as long as nobody looked. `tests/unit/test_vendored_assets_are_pinned.py` now
re-computes every hash in this block and fails on a mismatch, on a file listed
here that is missing, and on a vendored file this block never mentions —
INCLUDING one in a subdirectory. The first version of that gate used
`iterdir()`, which is not recursive, and a reviewer demonstrated it: a hostile
`vendor/dist/plugin.min.js` was served same-origin under `script-src 'self'`
while the gate reported `6 passed`. It uses `rglob` now. Update the block when
you refresh; do not delete the check.

**Why 14.1.1 rather than the 14.1.0 ADR-0014 named.** 14.1.0 is covered by a
`linkify` ReDoS advisory (GHSA-38c4-r59v-3vqw) fixed in 14.1.1. This app ships
`linkify: false`, so it was never reachable — measured on 14.1.0, 40,000
characters of adversarial input took 2,161.8 ms with `linkify: true` and 10.9 ms
as configured. The bump is defence in depth against the day someone decides bare
URLs should be clickable. `linkify: false` and `typographer: false` are
therefore SECURITY-relevant settings, not only fidelity ones.

```
c833317a56b17b17cc1910f3b7004447573487cd1fed4c1bcef90afbcbf5c234  markdown-it.min.js
c50b94bbc4f02394326fb7aed1f4fb693b3677f4b3d3344e0d6131808cbf281f  swagger-ui-bundle.js
8f33d996025317049d4a9864f421eab2b2a247872f388026fa94c654913259e7  swagger-ui.css
3ed612f41e050ca5e7000cad6f1cbe7e7da39f65fca99c02e99e6591056e5837  favicon-32x32.png
```

## Refreshing

```bash
cd src/product_app/static/vendor
MDI=14.1.1
SWG=5.18.2
curl -sSfo markdown-it.min.js    "https://cdn.jsdelivr.net/npm/markdown-it@${MDI}/dist/markdown-it.min.js"
curl -sSfo swagger-ui-bundle.js  "https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWG}/swagger-ui-bundle.js"
curl -sSfo swagger-ui.css        "https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWG}/swagger-ui.css"
curl -sSfo favicon-32x32.png     "https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWG}/favicon-32x32.png"
shasum -a 256 *.js *.css *.png   # then update the block above
```

After refreshing, re-run the checks that actually exercise these files:

```bash
# the checksum + provenance gate (hermetic, offline)
uv run pytest -q tests/unit/test_vendored_assets_are_pinned.py

# Swagger UI: same-origin asset URLs, and it renders under the real CSP
uv run pytest -q tests/integration/test_docs_self_hosted.py
cd e2e && npx playwright test tests/docs/docs-under-csp.spec.ts --project=chromium

# markdown-it: the whole failure corpus, plus the XSS pin
cd e2e && npx playwright test tests/invariants/markdown-corpus.spec.ts \
  tests/invariants/rendering-invariants.spec.ts --project=chromium
```

A `markdown-it` refresh is the one that can break quietly: `app.js` reaches into
the parser's delimiter list to suppress intra-word `*` emphasis (ADR-0015,
deviation 3). That is internal API. The corpus spec is what proves it still
works — run it before trusting a version bump.
