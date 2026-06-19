# Code Style Policy

- Use small modules with explicit ownership.
- Prefer simple, typed, testable functions.
- Use Ruff for formatting/linting and mypy or pyright for type checking.
- Avoid hidden global state except configuration loaded at startup.
- Public APIs require backward-compatibility review.
