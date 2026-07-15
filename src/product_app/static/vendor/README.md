# Vendored interactive-docs assets

These files are served same-origin under `/static/vendor/` so the app's strict
Content-Security-Policy never has to allow a third-party CDN. FastAPI's built-in
`/docs` and `/redoc` load Swagger UI / ReDoc from `cdn.jsdelivr.net` (and a
favicon from `fastapi.tiangolo.com`), every one of which the CSP blocks — so the
stock docs render blank. `main._register_docs_routes` serves custom `/docs` and
`/redoc` that point at the copies here instead.

## Provenance (pinned)

| File | Upstream | Version |
|---|---|---|
| `swagger-ui-bundle.js` | `swagger-ui-dist` (npm, via cdn.jsdelivr.net) | 5.18.2 |
| `swagger-ui.css`       | `swagger-ui-dist` (npm, via cdn.jsdelivr.net) | 5.18.2 |
| `redoc.standalone.js`  | `redoc` (npm, `bundles/`, via cdn.jsdelivr.net) | 2.1.5 |
| `favicon-32x32.png`    | `swagger-ui-dist` (npm, via cdn.jsdelivr.net) | 5.18.2 |

## SHA-256 checksums

```
c50b94bbc4f02394326fb7aed1f4fb693b3677f4b3d3344e0d6131808cbf281f  swagger-ui-bundle.js
8f33d996025317049d4a9864f421eab2b2a247872f388026fa94c654913259e7  swagger-ui.css
be5c3330c8c35b8fceb29a5b7552ad45bffc2fd9494fe2e1a82fa94179eb5f8f  redoc.standalone.js
3ed612f41e050ca5e7000cad6f1cbe7e7da39f65fca99c02e99e6591056e5837  favicon-32x32.png
```

## Refreshing

```bash
cd src/product_app/static/vendor
SWG=5.18.2 RDC=2.1.5
curl -sSfo swagger-ui-bundle.js "https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWG}/swagger-ui-bundle.js"
curl -sSfo swagger-ui.css       "https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWG}/swagger-ui.css"
curl -sSfo favicon-32x32.png    "https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWG}/favicon-32x32.png"
curl -sSfo redoc.standalone.js  "https://cdn.jsdelivr.net/npm/redoc@${RDC}/bundles/redoc.standalone.js"
shasum -a 256 *.js *.css *.png   # then update the table above
```

After refreshing, re-run the docs tests and load `/docs` + `/redoc` in a browser
(the tests assert same-origin asset URLs; a real browser confirms they render):

```bash
PYTHONPATH=src SENTRY_DSN='' .venv/bin/python3 -m pytest -q tests/integration/test_docs_self_hosted.py
```
