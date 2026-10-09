# W54 research 3b: cryptography for encrypted PDFs, octet-stream PDFs, the 15,000 sweep

A research agent's results for the session (2026-10-09), copied here because the session's scratch
folder does not survive a restart. Its scripts and throwaway environments were not kept.

Repo read at main 13e5cdd (read-only). Measurements on this Mac (Darwin 25.6, arm64),
CPython 3.12 from uv, throwaway venvs in this folder. Grades: MEASURED / SOURCED / INFERRED.

## 1. cryptography

- Version 50.0.2 (uploaded 2026-09-30), licence `Apache-2.0 OR BSD-3-Clause`.
  Requires `cffi>=2.0.0` (non-PyPy); cffi pulls `pycparser`. MEASURED (PyPI JSON; `uv pip install`
  printed cffi 2.1.1, cryptography 50.0.2, pycparser 3.1; pycparser 3.11 was uploaded on 2026-10-09 and is
  the version `uv.lock` records).
- Linux x86_64 wheel for CPython 3.12 is abi3: `cryptography-50.0.2-cp311-abi3-manylinux_2_34_x86_64.whl`,
  4,752,576 bytes (also manylinux_2_28 4,753,050; manylinux2014 4,719,841). MEASURED (PyPI JSON).
- The Linux wheel's `_rust.abi3.so` is 14,434,376 bytes, has OpenSSL 4.0.3 (29 Sep 2026) linked in
  statically, and needs only `libgcc_s.so.1`, `libc.so.6`, `ld-linux-x86-64.so.2`. Built-in paths:
  `OPENSSLDIR "/opt/pyca/cryptography/openssl"`, `MODULESDIR ".../lib64/ossl-modules"`. MEASURED
  (`strings`, `objdump -p` on the downloaded wheel).
- cffi's C extension `_cffi_backend` IS imported when cryptography loads. MEASURED (`-X importtime`;
  `sys.modules` check).
- Advisories in the last 12 months (gh api advisories, ecosystem pip): GHSA-m2h6-j472-rp4c (medium,
  <49.0.0), GHSA-jwv3-5hgf-82ww (high, <49.0.0), GHSA-g6cj-pr64-35w5 (high, PKCS#7 Bleichenbacher, <50.0.0),
  GHSA-537c-gmf6-5ccf (high, vulnerable bundled OpenSSL, <48.0.1), GHSA-p423-j2cm-9vmq (medium, <46.0.7),
  GHSA-m959-cc7f-wv43 (low, <46.0.6), GHSA-r6ph-v2qm-q3c2 (high, <=46.0.4). None affects 50.0.2.
  None is in the AES/RC4 decrypt path pypdf uses (X.509 / PKCS#7 / SECT curves / bundled OpenSSL).
  MEASURED (list); "not in pypdf's path" INFERRED from the summaries.
- pycryptodome: 3.24.0 installed; advisories: 2 ever (2018, 2024 OAEP side channel). Pure C via ctypes,
  no OpenSSL. MEASURED (gh api).
- pypdf 6.19.0 chooses: `_crypt_providers/__init__.py` tries `_cryptography` first, then `_pycryptodome`,
  then `_fallback` (pure-Python RC4; AES raises `DependencyError("cryptography>=3.1 is required for AES
  algorithm")`). MEASURED (source read in installed pypdf).
- pypdf 6.19.0 itself: the eight HIGH pypdf advisories published 2026-10-01 are all fixed at or below
  6.19.0 (`< 6.19.0`, `< 6.18.1`, `< 6.18.0`, `< 6.17.0`). MEASURED.

Residual risk (INFERRED): adding cryptography puts ~14 MB of native code (OpenSSL + Rust) into every PDF
child, because `import pypdf` imports the crypt provider eagerly (MEASURED: importtime shows
`pypdf._crypt_providers._cryptography` under `pypdf`). The bytes that reach OpenSSL are AES/RC4 key and
ciphertext only; no ASN.1/X.509 parsing. The child's limits still bound it. pycryptodome is a smaller
native surface for the same job, but cryptography is pypdf's first choice and the message production
printed names it.

## 2. Measured extraction (fresh `env -i python -s -B`, getrusage SELF, includes interpreter start)

| venv (bytecode) | PDF | chars | CPU s (median of 3-5) | peak RSS MiB |
|---|---|---|---|---|
| pypdf only, compiled | either PPC file | 0 (DependencyError) | 0.045 | 31.8 |
| + cryptography, compiled | 230602_kouhou_houdou (6 pages) | 4,115 | 0.077 | 39.0 |
| + cryptography, compiled | leaflet (1 page) | 860 | 0.062 | 38.7 |
| + pycryptodome, compiled | 230602 | 4,115 | 0.081 | 34.0 |
| + pycryptodome, compiled | leaflet | 860 | 0.064 | 33.8 |
| + cryptography, NOT compiled | 230602 / leaflet | 4,115 / 860 | 0.175 / 0.158 | 88 |
| import only (pypdf+provider), compiled | none / cryptography / pycryptodome | — | 0.044 / 0.048 / 0.048 | 31.3 / 35.2 / 32.1 |

- Under the real `pdf_text.set_limits()` (RLIMIT_CPU (2, 3) confirmed by getrlimit) both files extract
  in full; a busy loop after extraction is killed with exit 152 (SIGXCPU), so the limit was live.
- Japanese text is readable; 0 characters in U+0080–U+00FF (garble share 0.0); 0 U+FFFD; 0 private-use.
  First 200 characters (230602): "News Release 公表資料 生成 AI サービスの利用に関する注意喚起等について 令和５年 ６月２ 日
  我が国において、現在、生成 AI サービス（質問・作業指示（プロンプト入力）等 に応えて文章・画像等を生成する AI を利用したサービス）が普及していることを踏 まえ、..."
- RLIMIT_AS cannot be set on macOS; VmPeak on Linux UNMEASURED.

## 3. Encryption

- 230602: `/V 5 /R 6` AES-256 (`/AESV3`); leaflet: `/V 5 /R 5` AES-256 (the deprecated Adobe ext. 3
  revision). Both `decrypt("")` → 1 (user password is empty); `/P -1324` has bit 5 (copy/extract) set.
  MEASURED.
- pypdf auto-tries the empty password when none is given (`_handle_encryption`, `pwd = b""`). MEASURED (source).
- Built test files with user password "" vs "s3cret", five algorithms: with cryptography or pycryptodome
  every empty-password file reads (860 chars), every real-password file gives 0 (pypdf raises
  `FileNotDecryptedError`, caught → "" → `unusable`). With neither library: RC4-40 and RC4-128 read
  (pure-Python fallback), all AES-128 / AES-256 / AES-256-R5 give 0. MEASURED.
- RC4 through cryptography's OpenSSL (decrepit ARC4) works under `env -i` on macOS. MEASURED. Linux
  UNMEASURED; pypdf falls back to pure-Python RC4 if OpenSSL refuses (source).
- pypdf ignores the owner's permission bits: a file with extraction NOT permitted (P=4) still extracts
  860 chars. MEASURED. (The PPC files permit extraction anyway.)

## 4. octet-stream

Sources: WHATWG MIME Sniffing §7.1 (https://mimesniff.spec.whatwg.org/) — PDF pattern `25 50 44 46 2D`,
"leading bytes to be ignored: none". RFC 8118 (https://www.rfc-editor.org/rfc/rfc8118.html) — magic
"All PDF files start with the characters %PDF-", deprecated aliases "none". MDN
(https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/MIME_types) — octet-stream "is the default for
binary files". Adobe implementation note quoted in TIKA-1085 (https://issues.apache.org/jira/browse/TIKA-1085):
"Acrobat viewers require only that the header appear somewhere within the first 1024 bytes"; Tika
then matched `%PDF-` at offset 0:1024. NetApp StorageGRID KB: default S3 PUT Content-Type is
`binary/octet-stream`. Amazon S3's own default: not found in AWS docs (UNVERIFIED).
`application/force-download`, `application/x-download`: unregistered, used by PHP "force download"
scripts (forum sources only; frequency UNMEASURED).

pypdf (MEASURED): non-strict mode only warns when byte 0 is not `%PDF-`. With junk prepended:
3-4 bytes → both files read; 100 / 1,006 / 1,100 bytes → the 230602 PPC file gives 0 chars, the leaflet
(also AES-256, R5; see §3) still gives 860. Round-1 review: the leaflet re-encrypted as RC4-128 or AES-256
also gives 860 at every size. The repository's six empty-password fixtures read in full (441 characters)
at 0, 4, 100, 1,006 and 1,100 junk bytes of `J`, space, NUL or newline; with 1,006 or more `x` bytes,
AES-128, RC4-40 and RC4-128 read 0 while the three AES-256 fixtures still read (measured by the session,
2026-10-09, with `pdf_text.extract_text`). So the drop depends on the file and the junk bytes, not on
AES. (This line first said "the RC4 leaflet", and then wrongly "the fixtures give 441 at 0-1,006 junk
bytes".)

Robots path (MEASURED by reading source): `fetch_cited_pages.permit()` calls `_fetch_one(..., raw=True)`
without `long_pages` (default False); `is_pdf = content_type == PDF_CONTENT_TYPE and long_pages and not raw`.
Any new octet-stream rule must keep `long_pages and not raw`.

Design trap (INFERRED from source): the cap (`max_pdf_bytes` vs `max_bytes`) is chosen BEFORE the body is
read, but `%PDF-` can only be checked after. Check the first bytes as they arrive and refuse at once, or
an octet-stream ZIP/EXE is downloaded up to 4 MiB before refusal. `read1(8192)` can return fewer than 5
bytes, so accumulate until ≥5 bytes.

## 5. Sweep for 8,400 / cost_judge_input_tokens_with_pages / CHG-032 (d)

CHG-035 and CHG-036 do not exist in the tree at 13e5cdd (MEASURED, git grep count 0).

Code: src/product_app/config.py:643-651 (default 8400, comment cites CHG-032 (d), "a rounding of the larger
of the two judge inputs"); src/product_app/costs.py:2448-2455 (comment only, reads the setting);
.env.example:367-371 (COST_JUDGE_INPUT_TOKENS_WITH_PAGES=8400).
Tests: tests/unit/test_w54_page_reserve_one_token_per_char.py lines 12, 228, 236, 247-252, 258-259,
285-288, 296, 304-305, 346-352, 365, 491.
Docs: docs/adr/0152-unreadable-pages-are-checked-by-their-preview-and-the-judge-reserve-counts-page-text-at-one-token-per-character.md:7, 58, 60-61, 153 (title "8,400", "$0.0004 more than 7,300");
docs/analysis/2026-10-08-w54-step2-previews-and-reserve-failure-modes.md:5-6, 27;
docs/19-change-control-log.md:36 (CHG-032 (d) verbatim owner answer — history, do not edit; add CHG-036);
docs/65-open-work.md:151 (W54 row "the typical judge input 8,400").

MEASURED by running the full suite on a `git archive` copy with the default set to 15000
(`.env.example` too): 12 failed, 6239 passed, 76 skipped. 6 of the 12 also fail on the same copy at 8400
(copy has no origin/main: test_open_work_matches_reality x4, test_replay_scope..., test_mutation_copy...),
so the change turns exactly 6 tests red, all in test_w54_page_reserve_one_token_per_char.py:
setting default (15000 != 8400); typical 0.01575825 (was 0.00915825) twice; query 4000 → 0.01675,
20000 → 0.02075; headline 0.2085 (was 0.2019). The clamp test still passes (15,000 + 5,000 < ~61,000).
Production delta at $0.40/M input: +$0.00264 per estimate vs 8,400, +$0.00308 vs 7,300 (arithmetic).
e2e specs not run.

Real parent path (`source_fetcher.read_pdf_text`, env={}, -s -B) on the copy: before cryptography both
PPC files `unusable`; after `cryptography==50.0.2` 230602 `fetched` 4,115 chars (0.082 s warm), leaflet
`fetched` 860; AES-256 and RC4-128 real-password files stay `unusable`. MEASURED.

## 6. Other

- Dockerfile installs with `uv pip install .` from pyproject ranges, ignoring uv.lock (pyproject comment
  says so; MEASURED by reading). cryptography is in neither pyproject nor uv.lock (grep count 0), and is
  not in the test venv either. Pin it exactly, like pypdf; cffi/pycparser then float.
- Among the runtime packages, pypdf's crypt providers import cryptography; so can urllib3's optional
  `urllib3/contrib/pyopenssl.py` (round-1 review). The app never loads it: after a TestClient start and
  /health /ready /status /ui /ui/ops /metrics and a POST to /v1/query-runs/estimate, none of cryptography, pypdf, cffi or pycparser
  is in `sys.modules` (round-1 review, MEASURED). (This line first said "Only pypdf's crypt providers".)
- If cryptography's .so fails to map under RLIMIT_AS, Python raises ImportError and pypdf silently falls
  back (INFERRED from the try/except ImportError chain) — AES PDFs would be unusable again with no error.
