# ADR-0147: The untrusted-text fence catches an altered marker

## Status

Accepted — 2026-10-05, board row W53, found by W52's round-2 reviewers. The design is the
session's; no owner decision was asked for, because no prompt, price or visible text changes.
Failure modes, written before the code:
`docs/analysis/2026-10-05-w53-fence-altered-marker-failure-modes.md`.

## Context

Untrusted text (answers, the user's previous question, debate and synthesis inputs, the
judge's evidence) is wrapped between `<<<UNTRUSTED_EVIDENCE_BEGIN>>>` and
`<<<UNTRUSTED_EVIDENCE_END>>>`. A system rule tells the model the block is data. Before
wrapping, `untrusted_text.neutralize_delimiters` replaces a forged marker inside the text with
`[redacted-delimiter]`, but only the EXACT marker. Reproduced on `88887ee`: a marker with
U+034F, U+FE0F, a Cyrillic `Е` or a space inside it passes unchanged. The judge also
neutralises each evidence line on its own (`evaluation._fenced_user_prompt`), so a marker split
across two lines is never seen whole. W29 will put web-search excerpts in the judge's prompt,
so this is fixed first.

## Decision

1. `neutralize_delimiters` finds a marker by its LETTERS, not its bytes. It reads the text as
   follows, keeping, for each character it reads, the position of the original character it
   came from:
   - NFKC normalisation (fullwidth forms, compatibility characters);
   - characters that are not letters or digits are skipped (spaces, punctuation, brackets,
     combining marks, variation selectors, invisible formatting characters), and so are the
     Hangul filler letters that render as blank (U+115F, U+1160, U+3164, U+FFA0);
   - a fixed look-alike map folds the Cyrillic and Greek letters that look like the marker's
     letters (B C D E G I N R S T U V) to Latin; it is a list of named characters, never a
     wildcard;
   - case is ignored.
   Where the letters read `UNTRUSTEDEVIDENCEBEGIN` or `UNTRUSTEDEVIDENCEEND`, the original
   span from the first to the last matched character, widened to take in any run of `<` or
   `>` (after NFKC) directly before or after it, is replaced with `[redacted-delimiter]`. So
   the exact marker is still replaced whole, byte for byte as before.
2. The output is never longer than the input: when the original span is shorter than the
   20-character replacement (NFKC turns one character into several, e.g. `ﬀ` into `ff`), the
   replacement is cut to the span's length. Texts are cut to their limits before they are
   fenced, so growth would break those limits.
3. The judge neutralises its joined evidence body once, through the same function, instead of
   line by line.
4. No prompt text changes: the markers, the system rules, the prompt ids and every price stay
   as they are.

## Rejected alternatives

- **Remove more characters before matching exact text** (W52's round-1 approach, extended).
  An exact match fails on any change; there is always one more character to remove. Round 2
  showed this.
- **A random tag in each call's markers** (e.g. `<<<UNTRUSTED_EVIDENCE_END 3f9a>>>`, with the
  rule saying only the tagged marker ends the block). Stronger: a forged closer cannot know the
  tag. But it changes the judge's system prompt (its pinned hash, prompt id and paid golden
  capture), the judge reserve (`$0.2949`, `$0.3283`, `$0.0334` in
  `tests/unit/test_bound_covers_the_judge.py`), the debate bound pins, and makes prompts
  differ call to call. Deferred to W29, which re-captures the judge anyway.
- **Treat every non-Latin letter as a possible look-alike.** It would match any run of 20 or
  more Cyrillic or Japanese letters and redact ordinary answers.

## Consequences

- Altered markers in every fenced text are redacted, in prompts only; nothing a user sees
  changes.
- Known false positive: prose that spells the marker's words in order, such as "untrusted
  evidence ending", loses those words inside the prompt.
- Known limits: paraphrase ("end of the untrusted block"), digit swaps (`UNTRU5TED`) and extra
  letters inside the words are not caught. Whether a model obeys any altered marker is
  untested.
- One more pass over each fenced text, linear in its length.
