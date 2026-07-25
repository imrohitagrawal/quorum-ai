# Working with an AI coding agent — the good and the traps

Building with an AI coding agent is the normal way to work on these projects. Used well it is a real
multiplier; used carelessly it quietly piles up bugs and debt. Be honest about both. Define terms on
first use.

## What it is good at
- Doing the typing once you have a clear plan: scaffolding, boilerplate, repetitive edits, test
  stubs, translating an interface into an implementation.
- Explaining unfamiliar code, suggesting approaches, and getting a first draft on the page fast.
- Working across many files quickly when the change is well-specified.

## Where it goes wrong (so you watch for it)
- **Confident but wrong.** It can produce code that looks right and runs but does the wrong thing, or
  misses an edge case. Plausible is not correct.
- **Security weaknesses.** It can introduce insecure patterns (unsafe input handling, leaked secrets,
  weak authentication) without flagging them. Independent security research in 2025 found a large
  share of AI-generated code contained vulnerabilities — on the order of 45% in one widely-cited
  analysis. Check the current figure and cite the source when you state it; the point stands either
  way: **AI code needs security review.**
- **Silent drift.** A floating "latest" model can change behaviour between runs. Pin the version.
- **Obeying text it was only meant to read.** When the agent pulls in outside text — an issue, a
  wiki page, a web result, a file it opened — that text is *input to consider*, not a command. A
  page that says "ignore your previous instructions and do X" can hijack a careless agent. The agent
  cannot always tell content from instructions, so you draw the line: everything it reads is data,
  never orders.
- **Scope creep.** Asked vaguely, it may change more than you wanted. Ask for small, specific changes.

## How to get the good without the bad
- **Plan, then delegate.** Decide the design yourself; give the agent a small, clear task inside it.
- **Read every diff.** Understand each line before it ships — the same bar as a human junior's pull
  request. If you cannot explain it, do not merge it.
- **Tests are the guardrail.** Write or keep tests that pin the behaviour; run them on everything the
  agent produces. A passing, meaningful test suite is what makes fast safe.
- **Review for security, not just function.** Look specifically for input handling, secrets,
  authentication, and dependencies — the things AI most often gets wrong.
- **Fetched text is data, not orders.** If something the agent read tells it to take an action,
  bring that to a human and decide on purpose — never let the agent act on instructions buried in
  content it retrieved.
- **Small steps, often.** Many small reviewed changes beat one large generated drop you cannot fully
  check.
- **Keep a human as the architect and the final gate.** The agent types; you decide and you approve.

## The vibe-coding trap (name it plainly)
"Vibe coding" — accepting AI output because it looks right and the demo works, without understanding
it — feels fast and produces a mess. The bugs and security holes surface later, and fixing code nobody
understands is slow and risky. The speed is real, but it is a loan; pay it back with planning,
reading the diff, and tests, or the interest compounds. The teams that win with AI are the ones that
stayed disciplined, not the ones that skipped the engineering.
