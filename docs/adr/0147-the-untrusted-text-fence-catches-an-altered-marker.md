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
   - NFKC normalisation (fullwidth forms, compatibility characters), then each character is
     decomposed (NFKD) and its accents (combining marks) are dropped, so a single-character
     `É` or `İ` reads as `E` or `I`, the same as `E` followed by a separate accent (review
     round 1 found the single-character form passing);
   - characters that are not letters or digits are skipped (spaces, punctuation, brackets,
     combining marks, variation selectors, invisible formatting characters), and so are the
     Hangul filler letters that render as blank (U+115F, U+1160, U+3164, U+FFA0);
   - a fixed look-alike map folds the Cyrillic and Greek letters that look like the marker's
     letters (B C D E G I N R S T U V) to Latin, both before and after upper-casing (so a
     lower-case `т` meets the mapped capital `Т`); it is a list of named characters, never a
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
   line by line. This changes nothing reachable today: a review-round-1 reviewer reported
   building judge prompts with a marker split across every pair of adjacent parts and getting
   the same output both ways (reported, not reproduced here), because a label (`MODEL_ANSWER_1:`) or a source number (`[2]`) always sits between
   two parts. It guards a layout W29 may add, where excerpt text sits next to other text.
4. No prompt text changes: the markers, the system rules, the prompt ids and every price stay
   as they are.

## Rejected alternatives

- **Remove more characters before matching exact text** (W52's round-1 approach, extended).
  An exact match fails on any change; there is always one more character to remove. Round 2
  showed this.
- **A random tag in each call's markers** (e.g. `<<<UNTRUSTED_EVIDENCE_END 3f9a>>>`, with the
  rule saying only the tagged marker ends the block). Stronger: a forged closer cannot know the
  tag. But it changes the judge's system prompt (its pinned hash, prompt id and paid golden
  capture) and makes prompts differ call to call. Deferred to W29, which re-captures the judge anyway.
- **Treat every non-Latin letter as a possible look-alike.** It would match any run of 20 or
  more Cyrillic or Japanese letters and redact ordinary answers.

## Consequences

- Altered markers in every fenced text are redacted, in prompts only; nothing a user sees
  changes.
- Known false positives: any text whose letters, read with spaces, punctuation and emoji
  skipped, contain the marker's letters in order loses that stretch inside the prompt:
  "untrusted evidence ending" becomes `[redacted-delimiter]ing`, and the letters may run
  across words ("a fun, trusted evidence endpoint"). Review round 2 ran the change over every
  tracked UTF-8 file at `9cc53d8` (1,542 files, 21.8 million characters, the golden fixture
  included) and about 44 million characters of French, Turkish, Vietnamese, Greek and Russian
  prose: accent-dropping added no redaction there. Redaction works on whole characters, so
  when one character supplies the last letter of a marker and more letters after it (`Ǆ` reads
  as `DZ`), the whole character is redacted.
- Known limits: paraphrase ("end of the untrusted block"), digit swaps (`UNTRU5TED`), extra
  letters inside the words, and look-alikes outside the map are not caught: small capitals
  (`ᴜɴᴛʀᴜꜱᴛᴇᴅ`), regional-indicator letters, Cherokee, Armenian, `Đ`, and the Greek lunate
  sigma `Ϲ` (left out because NFKC turns it into `Σ`). Whether a model obeys any altered marker is
  untested.
- One more pass over each fenced text, linear in its length. Measured by the round-2 reviewer
  on `eb0cc6c`: English prose of 1, 2, 4 and 8 million characters took 0.023, 0.048, 0.094 and
  0.189 seconds; the worst case found, 2 million random code points with one marker, took 1.45
  seconds. The test bound is 5 seconds at 2 million characters.
- Two matches cannot overlap: no character's letters contain `D` or `N` followed by `U`
  (scanned on Unicode 15.0, 15.1 and 16.0), so no character can end one marker and start the
  next. A two-line guard keeps the output from growing if a later Unicode version adds one.
