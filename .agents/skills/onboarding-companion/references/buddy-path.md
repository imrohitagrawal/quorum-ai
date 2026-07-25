# Buddy path — zero to a first contribution

Write this as a patient guide that assumes nothing. Define every term on first use. Keep sentences
short and the tone calm and encouraging — "no question is too basic" is the rule.

**Open the page with a freshness stamp.** The first line under the title is a visible
`Last reviewed: YYYY-MM-DD` date in ISO form (the render contract, P2) — set it to the day you write
or revise the page. Setup steps and conventions drift faster than anything else in a project, so this
stamp is what lets the staleness check flag the page once it has aged out. Keep it ISO; the check
reads no other format.

## 1. The problem, in everyday terms
A short, plain explanation of what the project does and why it matters, with the words explained. The
reader should be able to say what the project is after this section.

## 2. Words you'll need
A tiny glossary of the terms used in setup and the codebase (repository, branch, commit, pull request,
dependency, environment variable, API key, build, test). Define each in one plain line.

## 3. Set up the tools from zero
A numbered checklist that takes the reader from a blank machine to ready:
1. Install the tools (languages, package manager, the editor, the CLI).
2. Get access (the accounts and permissions, and **how to request them** — point to the right person
   or system).
3. Clone the repository.
4. Install dependencies.
5. Set up configuration and secrets — **the reader does the secret steps themselves**, the secure way
   (a secrets manager or local env file that is never committed). Never enter a key on their behalf;
   never put a secret in a doc. Show *where* secrets go and *how* to get them, not the secret itself.
6. Confirm the setup with a quick check command, and say what success looks like.

## 4. Run it end to end (the quickstart)
The single fastest path to seeing it work — ideally one command. Number the steps and say exactly what
the reader will see when it works. This first success builds confidence; put it early.

## 5. How to read the repo, in order
Do not drop the reader into a maze. Give a **guided route**:
1. Start here (the README and the project profile).
2. Then the architecture overview and the main entry point.
3. Then follow one path through the code (intake → process → output, or the request lifecycle).
4. Where the decisions are explained (the ADRs / decision log) and how to read them.
Tell the reader what each stop teaches and roughly how long it takes.

## 6. How to work, day to day
The habits that keep contributions smooth:
- **Plan first.** Write down what you are going to do before you change code. A few lines is enough.
- **Small steps.** Make one small change, run it, confirm it, commit. Repeat. Small changes are easy
  to review and easy to undo.
- **Read the diff before you commit.** Look at exactly what changed; understand every line — including
  anything an AI agent wrote for you.
- **Ask, don't assume.** If a requirement or an interface is unclear, ask. A five-minute question
  beats a day of rework.
- **The tests are the spec.** Run the tests; read them to learn what the code must do; add a test for
  anything new.
- **Follow the project's conventions** (where requirements live, where docs go, branch naming, the
  pull-request checklist).

## 7. What to do when you're stuck
A calm flow:
1. Read the exact error message slowly — it usually says what is wrong.
2. Check the obvious things (dependencies installed, environment set, on the right branch, services
   running).
3. Search the repo and the docs for the error or the symptom.
4. Reproduce it in the smallest possible way.
5. Still stuck after a short, honest try? **Ask** — say what you expected, what happened, and what you
   already tried. No question is too basic.

## 8. Follow one feature end to end
Pick one real, small feature and trace it from start to finish: the requirement → the promises it must
keep → the test that checks them → the code that makes it pass → it running. Seeing one whole slice is
what makes the project's shape finally click.

## 9. Your first contribution (a checklist)
A short "definition of done" for a first change:
- It is small and does one thing.
- It has a test (or updates one).
- The existing tests pass.
- You read the whole diff and understand it.
- It follows the conventions and the pull-request checklist.
- You asked for review and addressed the comments.
