# Incident Response

Process: detect → triage → mitigate → communicate → resolve → review →
follow-up work.

How each step is grounded in this repo today:

- **Detect**: `availability-check.yml` failure email (readiness);
  `deploy-drift-watchdog.yml` issue (pipeline); `/ui/ops` tiles; degraded
  banner (user-facing honesty).
- **Triage/mitigate**: the matching runbook in `docs/runbooks/` (index:
  `docs/83-runbook.md`).
- **Review**: a post-incident record with named sources — the worked
  example is `docs/runbooks/live-provider-outage.md`; unverifiable details
  are marked "not recorded", never reconstructed.
- **Follow-up**: tracked in the bug ledger (`docs/analysis/01-bug-ledger.md`)
  and GitHub issues.

## Replacing a secret

The order when a secret may have leaked: **revoke it first, then replace it.** A short outage of
the feature that uses it is better than a working leaked key. When it has not leaked (a routine
rotation), replace first and revoke after, so nothing goes down.

The production secrets are Fly secrets of the app `quorum-ai`, except the deploy token, which is
a GitHub secret. `fly secrets set` redeploys the app on its own, so a new value takes effect with
that deploy. Set a value from a command or a variable, never typed as a literal, so it stays out
of shell history (see `DEPLOY.md`, "Rotate the token secret").

| Secret | Used for (where it is read) | Replace it at | What replacing it does |
|---|---|---|---|
| `OPENROUTER_API_KEY` | model calls (`src/product_app/config.py`) | OpenRouter's key settings | Runs started after the deploy use the new key |
| `QUORUM_EVAL_JUDGE_API_KEY` | the optional answer judge, an OpenRouter key (`config.py`, `src/product_app/evaluation.py`) | OpenRouter's key settings | As above, for the judge |
| `TAVILY_API_KEY` | the optional web-search fallback (`config.py`) | Tavily's key settings | As above, for search |
| `GOOGLE_OAUTH_CLIENT_SECRET` | the sign-in code exchange (`src/product_app/google_signin.py`) | the OAuth client in the Google Cloud console | Sign-ins started after the deploy use the new secret |
| `QUORUM_TOKEN_SECRET` | signing cost-confirmation tokens (`src/product_app/costs.py`); keying each network's anonymous daily allowance and a deleted account's 24-hour spend carry (`src/product_app/session_store.py`); required at startup outside local runs (`config.py`) | `openssl rand -hex 32` | Confirmation tokens issued in the last 5 minutes stop working; every network's anonymous daily allowance, and its running total held in memory, starts again (ADR-0144); an account deleted before the change and re-created after it starts with a fresh allowance (ADR-0136). Sessions and live accounts' allowances are not affected |
| `INVITE_LINK_SIGNING_KEY` | signing invite links (`src/product_app/invite_links.py`) | at least 32 random characters | Every invite link issued so far stops working (`config.py`) |
| `SENTRY_DSN` | error reporting (`config.py`) | the Sentry project's client keys | Errors after the deploy go to the new key |
| `FLY_API_TOKEN` | the deploy job (the GitHub environment `production`) | `fly tokens create deploy`, then the environment's secret | The next deploy uses the new token; revoke the old one with `fly tokens revoke` |

After any replacement: check that the deploy finished and `GET /ready` answers, then revoke the
old value at its provider if that is not done yet. If the value was ever committed, assume it
leaked even if the commit was removed: GitHub keeps pull-request history, and secret scanning
alerts are listed under the repository's Security tab.
