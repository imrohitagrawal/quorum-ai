# W53 — the untrusted-text fence catches an altered marker: failure modes before the code

Written 2026-10-05, before the change. This is AGENTS.md rule 16e: the change is a prompt-injection defence. Board row W53 was found by W52's round-2 reviewers. Design: ADR-0147.

## Mechanism today (read on `ace6109`)

- `untrusted_text.neutralize_delimiters` replaces only the exact strings `<<<UNTRUSTED_EVIDENCE_BEGIN>>>` and `<<<UNTRUSTED_EVIDENCE_END>>>` with `[redacted-delimiter]`.
- `fence()` neutralises, then wraps. Callers:
  - the follow-up context (`providers.py`);
  - debate (`debate.py`);
  - synthesis (`synthesis.py`).
- The judge has its own builder, `evaluation._fenced_user_prompt`. It neutralises EACH evidence line separately, then joins them.
- Reproduced on `88887ee`: a marker with any of these inside it passes `neutralize_delimiters` unchanged:
  - U+034F;
  - U+FE0F;
  - a Cyrillic `Е`;
  - a space.

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | An altered marker passes the fence. The alteration can be a combining mark, a variation selector, an invisible character, a look-alike letter, fullwidth forms, a different space, a case change, or missing brackets. | A model may read it as the real closer and treat the text after it as instructions. Whether a model obeys one is untested. | Match the marker after normalising: NFKC; drop invisible and combining characters; fold a fixed look-alike map for the marker's letters; ignore case and anything that is not a letter or digit. Then redact the ORIGINAL span. |
| 2 | A marker split across two judge evidence lines. | Neutralising line by line never sees the whole marker. | The judge neutralises the joined body, once, through the shared function. |
| 3 | Redaction makes text longer. | Several texts are cut to a character limit BEFORE they are fenced (`flatten_for_prompt(..., max_chars=...)` in `debate.py` and `synthesis.py`), so text that grew afterwards could exceed the size a bound assumed. | The replacement `[redacted-delimiter]` is 20 characters; a match is at least 20 letters after normalising, but NFKC can turn one character into several (a ligature, a Roman numeral), so the original span can be shorter. When it is, the replacement is cut to the span's length. A test pins "output never longer than input". |
| 4 | Ordinary prose is redacted. Example: "untrusted evidence ending". | A legitimate answer loses a few words inside a prompt. It is never shown to the user, because only prompts are neutralised. | Accept the near-miss. Text must spell UNTRUSTED EVIDENCE BEGIN/END in order. Look-alike folding is a fixed map, never a wildcard, so long Russian or Japanese text is kept. A test pins this. |
| 5 | A prompt's bytes, hash, prompt id or price move. | A paid re-capture and moved money pins. | No prompt text changes. The judge prompt hash test stays green unchanged. |
| 6 | Cost of the check on long text. | Latency per prompt. | One linear pass per fenced text, which is at most a few hundred KB. A test bounds it on a large input. |
| 7 | Paraphrase ("end of the untrusted block"), digit swaps ("UNTRU5TED"), or extra letters inside. | Not caught. | Recorded as a known limit. A per-call random tag in the markers is the stronger answer, deferred to W29, which re-captures the judge anyway. ADR-0147 records the rejected option. |
