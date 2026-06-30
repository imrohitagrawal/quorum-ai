---
name: deploy-checklist
description: Pre-deploy and post-deploy checklist skill. Ensures env vars, migrations, CI, rollback plan, smoke tests, and monitoring are verified before and after every deployment.
license: MIT
metadata:
  author: wednesday-solutions
  version: "1.0"
permissions:
  allow:
    - Bash(npm run lint)
    - Bash(npm run format:check)
    - Bash(npm run test)
    - Bash(npm run build)
    - Bash(curl *)
    - Bash(gh run list)
    - Bash(gh pr checks)
---

# Deploy Checklist Skill

## When to use

- Pre-deployment verification for any environment
- Post-deployment smoke testing and validation
- Rollback assessment and execution
- Production incident response
- Deployment safety reviews

## When not to use

- **Code commits**: Use git/commit skill instead
- **PR creation**: Use pr-create skill instead
- **Project planning**: Use greenfield/planning skills instead
- **Debugging runtime issues**: Use debugging tools instead
- **Code review**: Use code-review skill instead

## Trigger

Load this skill when a dev is about to deploy or has just deployed:
- "We're deploying to production"
- "Pre-deploy check"
- "Post-deploy verification"
- "Run the deploy checklist"
- "Is it safe to deploy?"

**Do NOT use this skill for:** committing code (use `git-os`), creating a PR (use `pr-create`), or planning a project (use `greenfield`). This skill only applies at the deployment stage — code is already merged.

---

Run this checklist before and after every production deployment.

## Pre-Deploy Checklist

- [ ] All CI checks green on the deploy branch
- [ ] Environment variables verified in target environment (no missing keys)
- [ ] Database migrations reviewed — irreversible migrations documented
- [ ] Migrations have been dry-run or tested in staging
- [ ] Rollback plan documented: what to revert and how
- [ ] Feature flags set correctly for the release
- [ ] Downstream services notified if API contracts changed
- [ ] Changelog updated with this release's changes
- [ ] Deployment window confirmed (avoid peak traffic)

## Deploy

- [ ] Deploy initiated with correct branch / tag
- [ ] Deployment logs monitored in real time
- [ ] No unexpected errors during startup

## Post-Deploy Checklist

- [ ] Smoke test: critical user flows verified manually or via synthetic monitoring
- [ ] Health check endpoint returns 200
- [ ] Error rate in monitoring (Datadog, Grafana, Sentry) is normal
- [ ] No spike in latency or DB query time
- [ ] Monitoring alerts reviewed — no new alerts triggered
- [ ] Changelog published / communicated to stakeholders
- [ ] Ticket status updated (closed / released)

## Rollback Trigger Criteria

Initiate rollback immediately if:
- Error rate rises above 1% of requests
- P95 latency increases by more than 2x baseline
- Any data integrity issue detected
- Critical feature path returns 5xx

## Tools

| Action | Tool |
|--------|------|
| Run lint, test, build scripts | `Bash` |
| Check health endpoint | `Bash` — `curl -s <url>/health` |
| Read config or env files | `Read` |
| Check CI status | `Bash` — `gh run list` or `gh pr checks` |

## Notes

- Never deploy on Fridays unless it's a critical hotfix
- Always have a second engineer available during production deploys
- Document the actual deploy time and outcome in the ticket

## Inputs

- **Deployment context** (required): Target environment (staging/production)
- **Deployment type**: Greenfield, hotfix, or routine
- **Deployment artifacts**: Build artifacts, Docker images, database migrations
- **Previous deploy info**: Last successful deploy for comparison

## Owned outputs

- **Pre-deploy checklist**: Verified state of deployment prerequisites
- **Post-deploy checklist**: Verified state of deployment success
- **Rollback assessment**: Decision to proceed or rollback
- **Deployment report**: Summary of what was deployed and when

## Allowed tools

- `Bash` — Run lint, test, build scripts
- `Bash` — Check health endpoints via curl
- `Bash` — Check CI status via gh CLI
- `Read` — Read config files, env files, changelogs
- `Glob` — Find relevant deployment files

## Forbidden actions

- **Direct production edits**: Never modify production config without explicit approval
- **Forced deploys**: Never bypass failing checks
- **Ignoring rollback criteria**: Always rollback if trigger criteria are met
- **Deploying without documentation**: Always document the deployment in the ticket

## Procedure

1. **Confirm deployment context**: Environment, artifacts, and purpose
2. **Run pre-deploy checklist**: Verify all prerequisites
3. **Assess rollback readiness**: Document rollback procedure
4. **Execute deployment**: Initiate deploy with monitoring
5. **Run post-deploy checklist**: Verify success
6. **Document outcome**: Update ticket with results

## Quality bar

- **Completeness**: Every checklist item must be verified or explicitly skipped with reason
- **Accuracy**: Deployment artifacts and versions must match the release
- **Safety**: Rollback procedure must be documented before proceeding
- **Communication**: All stakeholders must be notified of deployment status

## Validation

- All CI checks must be green before deploy
- Health endpoint must return 200 after deploy
- Error rates must be within normal parameters
- No rollback triggered within 30 minutes of deploy

## Handoff contract

- **To Monitoring**: Alert on rollback trigger criteria
- **To Operations**: Document deploy time and artifacts in ticket
- **To Support**: Notify of any deployment-related user impact

## Stop conditions

- Any CI check fails → Stop and investigate
- Rollback trigger criteria met → Execute rollback immediately
- Deployment times out → Stop and investigate
- User cancels deployment → Stop and document state

## Examples

### Example 1: Pre-Deploy Verification
**Context**: "We're deploying v2.3.0 to production"
**Response**: "Pre-deploy check complete. All CI green. Env vars verified. Migrations reviewed and tested. Rollback plan: revert to v2.2.9. Ready to deploy."

### Example 2: Post-Deploy Smoke Test
**Context**: "Deployment finished"
**Response**: "Health check: 200 OK. Error rate: 0.1% (normal). Latency: 45ms (baseline: 50ms). No new alerts. Deployment successful."

### Example 3: Rollback Triggered
**Context**: "Error rate spiked to 3%"
**Response**: "ROLLBACK TRIGGERED. Error rate 3% exceeds 1% threshold. Initiating rollback to v2.2.9. Investigating root cause."

## Anti-examples

### Anti-example 1: Skipping Checks
**Bad**: "CI was red but we deployed anyway since it's urgent."
**Good**: "CI failed on integration tests. Deferring deploy until tests pass. Urgent: consider hotfix if critical."

### Anti-example 2: No Rollback Plan
**Bad**: "Let's deploy and see what happens."
**Good**: "Rollback plan documented: revert Docker image to sha-abc123, run db migration rollback script. Ready to proceed."

### Anti-example 3: Skipping Notification
**Bad**: "Deployed and forgot to update the ticket."
**Good**: "Deployed at 14:32 UTC. Ticket updated. Slack notification sent to #deployments."
