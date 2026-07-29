<!--
This template is INFLUENCE, NOT ENFORCEMENT. It sits above the line in
docs/DAY-ONE-PROMPT.md §1: GitHub cannot require any field here, so nothing in
this file can compel anything. Its only job is to make an invisible habit
visible. The gates that actually bind are in .github/workflows/.

It asks for pasted evidence rather than ticked boxes on purpose. This repo's
four most expensive recurring failures, in order of cost
(docs/metrics/mutation-gate-study.md §8, docs/103-incident-learnings.md), are:
claims made from reading rather than running; tests that pass whether or not
the feature works; advisory gates believed without opening the log; and numbers
written into prose without being measured. A checkbox cannot detect any of
them — every one of those failures would have been ticked off honestly by
someone who believed the claim. A pasted command and its output can be checked
in five seconds.

Delete a section only if it genuinely does not apply, and say so in one line.
"n/a — docs only" is a complete and acceptable answer.
-->

## What changed, and why

<!-- Two or three sentences. What was true before, what is true now. -->

## What I ran

<!--
The commands, and what they printed. Not "tests pass" — the actual numbers.
Paste real output; a summary of output is prose, and prose is the thing that
has been wrong here.
-->

```

```

## Which test would fail without this change

<!--
Name the test, then say which line you broke to prove it goes red. If you
changed no behaviour, write "no behavioural change" and say what does cover it.

The procedure, because a test that passes when the feature is absent is worth
nothing: `cp` the file aside, break the line, run the test, restore from the
copy, `diff -q` to confirm the restore. Never `git checkout <file>` — the tree
may hold uncommitted work.
-->

- Test:
- Line I broke to see it go red:
- Confirmed the run actually executed (not a collection error):

## Gate results I opened

<!--
Only for gates whose result you are relying on. A green tick is not a result
and neither is a red one — both can mean the job fell over before measuring
anything (#158). Give the job log link and the number it printed, or write
"did not rely on any gate result".
-->

- Gate:
- Job log:
- The number it printed:

## What I did not do

<!--
Left deliberately, filed as an issue, or knowingly unverified. "Nothing" is a
valid answer; an omission here that surfaces later in review is not.
State any claim you could not verify as UNVERIFIED, with the check that would
settle it.
-->
