# Mentor path — the senior-engineer mindset

This section passes on the judgement that takes years to learn, in plain words. Write it as a senior
engineer talking to someone they want to see succeed — direct, kind, and honest. Define terms on first
use.

## The core mindset: treat an AI coding agent as a fast junior
An AI coding agent is quick, tireless, and confident — but confidence is not correctness. Treat its
output the way you would treat a fast junior's: useful, often right, sometimes subtly wrong, and
always to be checked.
- **Verify, don't trust.** Read everything it produces. Understand every line before it ships. If you
  cannot explain it, you cannot own it.
- **You are the architect.** Decide the design, the boundaries, and the trade-offs yourself. Let the
  agent do the typing inside a plan you set, not the thinking.
- **You are the final gate.** Nothing reaches the main branch or production without your review and
  the tests passing.

## How to work
- **Plan first.** Decide what you are building and why before writing code. A short written plan
  catches bad ideas cheaply.
- **Small steps, shipped often.** Many small, reviewed changes beat one big drop. They are easier to
  review, easier to debug, and easier to undo.
- **Write decisions down.** When you make a real choice (a library, a structure, a trade-off), record
  it as a short **ADR** (Architecture Decision Record): the context, the options, the choice, and the
  consequences. Future-you and the next person will thank you.
- **Make the tests the contract.** Tests say what the code must do. Keep them green; add one for every
  new behaviour and every bug fixed.

## The things people skip and regret
- **No decision log.** Six months on, nobody remembers why — and they undo good decisions by accident.
  Keep the log.
- **Committing to main directly.** Protect the main branch; change it only through reviewed pull
  requests, so it always works.
- **Committing secrets.** Never put a key, password, or token in the code or the history — once pushed,
  treat it as leaked and rotate it. Use a secrets manager or an ignored local env file.
- **Optimising before measuring.** Make it correct, then measure, then speed up only what the numbers
  say is slow. Guessing wastes effort and adds complexity.
- **Ignoring cost.** AI calls and cloud resources cost money per use. Watch the spend; a cost spike is
  a real incident.
- **Floating model versions.** Pin the **exact model version** you depend on. "Latest" can change
  under you and quietly shift behaviour; upgrade deliberately, with tests.
- **Never paying down AI debt.** A coding agent produces working code fast, but fast work accrues
  debt — shortcuts, missed edge cases, code nobody fully understands yet. Left alone it compounds
  until the project is slow and fragile to change. Reserve a slice of every cycle for cleanup,
  refactoring, and tests — a rough rule of thumb is around a tenth — and treat it as a real cost you
  budget for, not a thing you will get to later.

## The project's conventions (fill from the profile)
State plainly, with links:
- Where **requirements** live and how they become work.
- Where **docs** live and the expectation to update them in the same change (docs in lockstep).
- Where **ADRs** go and how to add one.
- How **feature flags** work (ship code dark, turn it on safely).
- That **observability comes first** — you add the logs, metrics, and traces as you build, not after
  something breaks.

## Psychological safety
Say it directly: asking questions is how good engineers work, not a sign of weakness. The fastest path
to productive is to ask early, pair when useful, and treat every "obvious" question as fair. A team
that is safe to ask in is a team that ships.
