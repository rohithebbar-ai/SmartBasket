# ShopSense deployment checklist

Aligns with `ShopSense_Platform_Plan_v3.md` (repository §13, Terraform §14). Use before `terraform apply` or cutting a production release.

## Code & tests

- [ ] Tests pass for changed modules (`pytest` / frontend test script as applicable).
- [ ] `shopsense-code-reviewer` run on changed paths; no open CRITICAL issues on security-sensitive code.
- [ ] No secrets in git; `.env.example` updated if new vars exist; production secrets only via env or secret store.

## Container & runtime

- [ ] `docker compose` (or production compose override) builds and starts locally.
- [ ] Non-root user in container if Dockerfile defines one; minimal base image where possible.
- [ ] Health endpoint reachable behind Nginx as designed.

## AWS / Terraform

- [ ] `terraform plan` reviewed (no unintended destroys).
- [ ] `your_ip` variable correct for SSH rule; not `0.0.0.0/0` for SSH.
- [ ] Remote state bucket (`backend.tf`) reachable; state lock understood if team grows.
- [ ] Key pair name matches `main.tf` expectation; AMI/instance type appropriate for region.

## Data & messaging

- [ ] Database URL and migrations (if any) coordinated; backup before destructive migration.
- [ ] Kafka (if on server): topics and consumers start; no duplicate processing without mitigation.

## Observability

- [ ] Logs do not print tokens, DB URLs with passwords, or Groq keys.
- [ ] Metrics/tracing endpoints configured if Prometheus/LangSmith are in use.

## Rollback

- [ ] Previous image tag or artifact identified.
- [ ] Steps to revert Terraform or redeploy last good build written down (even briefly).
