# PDF extraction research — 2026-10-08 (the research agent's notes, copied into the repo)

> Read with `README.md`, which corrects these notes (round-1 review, 2026-10-08). Only the
> `.py.txt` scripts and the three `.jsonl` files listed in this folder were copied; `pdfs/`,
> `texts/`, `attacks/` and `full_10pages.jsonl` were not. `attacks.jsonl` is not a full 5 x 15
> grid (`a7c` has 4 libraries; `a3c` has 6 rows). The 26.8 s figure used 4 MB stream limits.

Machine: Apple Silicon Mac, 10 cores, load average 5-8 during runs (other sessions). Python 3.12.13.
Versions: pypdf 6.19.0, pdfminer.six 20260107, pdfplumber 0.11.10, pymupdf 1.28.2, pypdfium2 5.14.0.

Files
- pdfs/                     6 real PDFs (NIST AI RMF; 5 from ppc.go.jp, 4 Japanese)
- extract_one.py            one extraction per process; JSON line (wall, cpu, RSS delta, chars)
- full_10pages_notm.jsonl   timing table, 3 reps, NO tracemalloc (use this one)
- full_10pages.jsonl        same WITH tracemalloc (inflates pure-Python times 3-7x; do not quote)
- quality.py, texts/        per-library text dumps + CJK / mojibake counts
- trunc_clean.jsonl         truncated downloads (256 KiB, 512 KiB, 1 MiB): 0 chars from every library
- make_attacks.py, attacks/ hostile PDFs; run_attack.py samples child RSS, kills at 3 GB / timeout
- attacks.jsonl             attack results (5 libraries x 15 files)
- pypdf_limited.py          pypdf with Configuration stream caps
- sandbox_worker.py, sandbox_parent.py, sandbox_cpu_test.py  subprocess + rlimit prototype
- summarize.py              prints the timing table

Key measured facts
- Truncated PDF = unreadable for all 5 libraries, including linearized files at 1 MiB.
- pypdf garbles /90msp-RKSJ-H fonts (ppc_kihongensoku.pdf); mapping it to cp932 fixes it exactly.
- 13 KB PDF (10 pages sharing one 3.9 MB text stream): pypdf 26.8 s CPU even with 4 MB stream caps.
- 7 KB double-Flate bomb: pdfium / pdfminer > 3 GB RSS within 0.5-1 s; pypdf stops in 0.07 s.
- RLIMIT_CPU=2 killed the pypdf worker at 2.03 s (SIGXCPU); asyncio wall kill at 1.005 s.
- RLIMIT_AS cannot be set on macOS -> memory cap UNMEASURED; must be measured on Linux/Fly.
