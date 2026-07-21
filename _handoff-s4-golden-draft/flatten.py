#!/usr/bin/env python3
"""Flatten per-case golden files into a single golden-cases.json and report balance."""

import collections
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_DIR = os.path.join(HERE, "cases")

cases = []
for path in sorted(glob.glob(os.path.join(CASES_DIR, "*.json"))):
    with open(path) as f:
        d = json.load(f)
    if "cases" in d:
        cases.extend(d["cases"])
    else:
        cases.append(d)

# --- integrity checks ---
ids = [c["id"] for c in cases]
dupes = [i for i, n in collections.Counter(ids).items() if n > 1]
assert not dupes, f"duplicate ids: {dupes}"
assert 60 <= len(cases) <= 80, f"count out of range: {len(cases)}"

for c in cases:
    for req in (
        "id",
        "query_text",
        "category",
        "domain",
        "tags",
        "needs_human_label",
        "rationale",
        "fixture",
        "expected",
    ):
        assert req in c, f"{c.get('id')} missing {req}"
    assert (
        "initial_answers" in c["fixture"]
        and "final_synthesis" in c["fixture"]
        and "agreement" in c["fixture"]
    ), f"{c['id']} bad fixture"
    if c["needs_human_label"]:
        assert c.get("needs_human_label_reason", "").strip(), (
            f"{c['id']} needs_human_label true but no reason"
        )

# --- balance matrix ---
by_cat = collections.Counter(c["category"] for c in cases)
by_dom = collections.Counter(c["domain"] for c in cases)
cat_dom = collections.defaultdict(lambda: collections.Counter())
for c in cases:
    cat_dom[c["category"]][c["domain"]] += 1

has_ref = [c for c in cases if c.get("expected_sources") or c.get("ground_truth")]
nhl = [c["id"] for c in cases if c["needs_human_label"]]

# --- write consolidated corpus ---
out = {
    "meta": {
        "description": (
            "S4 golden set — HAND-AUTHORED, REAL-SHAPED fixtures for the S2 evaluation "
            "engine. NOT captured production runs. No case is a real run; no human label "
            "is fabricated. Cases needing a genuine operator label are flagged "
            "needs_human_label=true."
        ),
        "case_count": len(cases),
        "generated_by": "assembler (S4)",
        "loader_note": (
            "Each element of `cases` is one golden case in the tests/evals/golden schema. "
            "A production layout would split these one-per-file into "
            "tests/evals/golden/cases/<id>.json; a golden loader imports the "
            "corpus/loader.py case-building primitives so coverage is still derived by "
            "production functions."
        ),
    },
    "cases": cases,
}
outpath = os.path.join(HERE, "golden-cases.json")
with open(outpath, "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)

# --- report ---
print("TOTAL CASES:", len(cases))
print("\nBY CATEGORY:")
for k in sorted(by_cat):
    print(f"  {k:28s} {by_cat[k]}")
print("\nBY DOMAIN:")
tot = len(cases)
for k in ("general", "technical", "high_stakes"):
    print(f"  {k:12s} {by_dom[k]:3d}  ({100 * by_dom[k] / tot:.1f}%)")
print("\nCATEGORY x DOMAIN:")
print(f"  {'category':28s} {'gen':>4} {'tech':>4} {'hi':>4}")
for k in sorted(cat_dom):
    r = cat_dom[k]
    print(f"  {k:28s} {r['general']:>4} {r['technical']:>4} {r['high_stakes']:>4}")
print(
    "\nREFERENCE-BEARING (ground_truth or expected_sources):",
    len(has_ref),
    f"({100 * len(has_ref) / tot:.1f}%)",
)
print("\nNEEDS_HUMAN_LABEL=TRUE:", len(nhl))
for i in nhl:
    print("  -", i)
print("\nWROTE:", outpath, os.path.getsize(outpath), "bytes")
