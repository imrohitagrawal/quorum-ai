# PR2 RED-GREEN Proof

This document records the RED→GREEN transition for each of the five PR2
data-completeness changes. Each section names the code change, the test that
proves it, and the exact assertion that would fail if the change were reverted.

---

## Change 1: Removed `[:600]` excerpt slicing from synthesis answer excerpts

**File:** `src/product_app/synthesis.py`, `_user_prompt` method

**Before:**
```python
excerpt = (answer.answer_text or "").strip().replace("\n", " ")[:600]
```

**After:**
```python
excerpt = (answer.answer_text or "").strip().replace("\n", " ")
```

**Test:** `tests/unit/test_synthesis.py::test_user_prompt_includes_full_600_char_excerpt`

**Assertion that fails if reverted:**
```python
long_answer = "x" * 800
# ...build prompt via _user_prompt...
assert ("x" * 800) in user_prompt
```

With `[:600]` re-added, only 600 characters appear in the prompt and
`("x" * 800) in user_prompt` fails.

---

## Change 2: Removed `[:700]` excerpt slicing from synthesis debate round excerpts

**File:** `src/product_app/synthesis.py`, `_user_prompt` method

**Before:**
```python
excerpt = (round_output.critique_text or "").strip().replace("\n", " ")[:700]
```

**After:**
```python
excerpt = (round_output.critique_text or "").strip().replace("\n", " ")
```

**Test:** `tests/unit/test_synthesis.py::test_user_prompt_includes_full_700_char_debate_excerpt`

**Assertion that fails if reverted:**
```python
long_critique = "y" * 800
# ...build prompt via _user_prompt...
assert ("y" * 800) in user_prompt
```

With `[:700]` re-added, only 700 characters appear and the assertion fails.

---

## Change 3: Raised `SYNTHESIS_SECTION_MAX_TOKENS` from 800 to 3000

**File:** `src/product_app/synthesis.py`, line 88

**Before:**
```python
SYNTHESIS_SECTION_MAX_TOKENS = 800
```

**After:**
```python
SYNTHESIS_SECTION_MAX_TOKENS = 3000
```

**Test:** `tests/unit/test_synthesis.py::test_synthesis_section_max_tokens_is_workstream_two_value`

**Assertion that fails if reverted:**
```python
from product_app.synthesis import SYNTHESIS_SECTION_MAX_TOKENS
assert SYNTHESIS_SECTION_MAX_TOKENS == 3000
```

---

## Change 4: Raised `DEBATE_ROUND_MAX_TOKENS` from 700 to 2000 and removed `[:200]` answer slice

**File:** `src/product_app/debate.py`

**Token cap change** (line 51):

**Before:**
```python
DEBATE_ROUND_MAX_TOKENS = 700
```

**After:**
```python
DEBATE_ROUND_MAX_TOKENS = 2000
```

**Answer slice change** (line 449, `_debate_user_prompt`):

**Before:**
```python
excerpt = (answer.answer_text or "").strip().replace("\n", " ")[:200]
```

**After:**
```python
excerpt = (answer.answer_text or "").strip().replace("\n", " ")
```

**Tests:** `tests/unit/test_debate_orchestration.py`

1. `test_debate_round_max_tokens_is_2000` — asserts `DEBATE_ROUND_MAX_TOKENS == 2000`
2. `test_debate_user_prompt_includes_full_answer_excerpt` — builds a 500-char answer,
   calls `_debate_user_prompt`, asserts the full text appears (no truncation)

**Assertions that fail if reverted:**
```python
# Token cap:
assert DEBATE_ROUND_MAX_TOKENS == 2000  # fails if set back to 700

# Slice removal:
long_text = "x" * 500
# ...build prompt...
assert long_text in prompt  # fails if [:200] is re-added (only 200 chars present)
```

---

## Change 5: Added `shortened` field + `finish_reason` detection on `LiveProviderResult`

**File:** `src/product_app/providers.py`

Three sub-changes:

**a) `is_truncated` field on `LiveProviderResult`** (line 1001):

```python
is_truncated: bool = False
```

**b) `finish_reason == "length"` detection in `_post_messages`** (lines 806–814):

```python
is_truncated = False
try:
    choices = parsed.get("choices") if isinstance(parsed, dict) else None
    if isinstance(choices, list) and choices:
        is_truncated = (choices[0].get("finish_reason") or "") == "length"
except Exception:
    pass
return LiveProviderResult(
    answer_text=content, sources=citations, usage=usage, is_truncated=is_truncated
)
```

**c) `shortened` field on `InitialModelAnswer` threaded from `is_truncated`**:

```python
shortened: bool = False  # on InitialModelAnswer
# passed through _completed_answer and produce_initial_answer
```

**Tests:**

1. `tests/unit/test_providers.py::test_shortened_true_when_provider_signal_length`
   — asserts `answer.shortened is True` when provider signals truncation
2. `tests/unit/test_providers.py::test_is_truncated_set_when_finish_reason_length`
   — asserts `result.is_truncated is True` at the `_post_messages` layer

**Assertions that fail if reverted:**
```python
# Without finish_reason detection, is_truncated is always False:
assert result.is_truncated is True  # fails

# Without shortened threading, the field stays False:
assert answer.shortened is True  # fails
```
