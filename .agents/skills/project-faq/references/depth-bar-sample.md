# The depth bar — a fully-worked sample answer

Match this depth and shape for **every** answer (except the glossary). This sample uses a generic
project to show the pattern; the structure is what matters: *what it is → why it matters → how it
works step by step → how AI is used (if any) → the trade-off / what was not picked and why*, then the
**two example boxes**. Notice that every technical word is defined the first time it appears.

---

**What is this project, and how does it work?**

**The problem, in everyday terms.** Teams that build software face the same slow, error-prone job
over and over: turning a written description of what a feature should do into proof that it actually
does it. A person reads the description, thinks of everything that could go right or wrong, writes
the checks by hand, runs them, and then tries to remember which check belonged to which part of the
feature. It is slow, cases get forgotten, and at the end nobody can easily *prove* that every promise
the feature made was tested.

**What this project is.** It is a system that does that job with the help of AI. You point it at the
place where the written requirements live, and it works through the steps on its own, pausing for a
human at the important moments: read the requirement; pull out the exact promises that must be true
(these are called *acceptance criteria*); let a human check those promises; write the checks, first
in plain language and then as real automated tests; run them and record what passed and failed; and
draw a live map connecting each requirement to its promises, to its tests, to the latest result
(this map is called *traceability*).

**Why it matters.** The expensive part of building software was never typing the code; it was being
sure the code is correct and *staying* sure as it keeps changing. This project attacks exactly that:
it makes coverage honest and measurable, and it keeps the proof up to date automatically.

**How it works, step by step.** (1) It reads the requirement. (2) It extracts the promises. (3) A
human approves them — a safety gate, so the AI builds toward a checked target. (4) It writes the
tests. (5) It runs them. (6) It reports coverage *per promise*, not just per feature. (7) Signals
from the running product flow back so the riskiest things get tested first next time.

**How AI is used (and where humans stay in charge).** A cheaper AI model reads the requirement and
extracts the promises; a stronger model drafts the harder tests; another pass deliberately hunts for
the cases people miss (empty inputs, expired links, overlaps). Humans approve the promises and
approve the final merge; the AI never ships to the live product on its own. (A *model* here means an
AI system you send text to and get text back; a cheaper one is used for easy steps and a stronger one
only for hard ones, which keeps it affordable.)

**The trade-off — what was not picked, and why.** The tempting shortcut is "just ask an AI to write
some tests." That was rejected because it produces tests with no human-checked target, no link back
to the requirement, and no way to prove coverage — so you cannot trust it. The chosen design costs a
human approval step and more wiring, and buys trust: every test traces to an approved promise, and the
system even checks its own work.

> **In your project.** [Replace with the real, specific example — for instance: the first finished
> piece is the contracts package, already published; the next feeds one approved ticket through every
> step and shows its coverage in a small local database.]

> **Picture it in real life.** Think of a tireless assistant in a car factory. You hand it the design
> spec for a new car. It writes the safety checks, runs them on the production line, and keeps a chart
> showing every safety rule and whether the car passed — and it learns from real-world recalls to
> check the riskiest things first next time. The factory manager (you) still signs off at the key
> gates.

---

## What makes this "depth-bar" quality

- It is **several paragraphs**, not a sentence.
- It defines every term inline (acceptance criteria, traceability, model).
- It covers what → why → how → how-AI → trade-off.
- It states **what was not picked and why** (the honest engineering choice).
- It ends with **both** example boxes.

Apply the same shape to "why this technology", "how testing works", "how to set up", and every other
answer. Shorter topics are still multi-paragraph and still carry both boxes.
