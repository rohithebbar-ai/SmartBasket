---
name: shopsense-deployment-agent
description: Safe deployment workflow for ShopSense — Docker Compose locally, single EC2 image on AWS via Terraform, Nginx reverse proxy, env secrets, health checks, rollback mindset. Use when preparing a release, applying terraform, or verifying production readiness for this project.
---

# ShopSense — Deployment agent

ShopSense targets a **modular monolith**: one Docker image on EC2, Terraform-managed networking and static IP, optional Vercel for the React storefront. This skill is **safety-first**: verify before apply, and never deploy with unresolved CRITICAL review findings on touched surfaces.

## Instructions

1. **Pre-flight** — Working tree clean or intentional; tests green for changed areas; run `shopsense-code-reviewer` on delta paths (especially `app/search`, `app/agent`, `infra/`). Confirm `.env` / secrets are not committed and production vars are documented outside git.
2. **Understand target** — Local: `docker compose` per repo `docker-compose.yml`. AWS: `infra/terraform/` with `terraform init` → `plan` → `apply` (see §14 of `ShopSense_Platform_Plan_v3.md`). SSH restricted by `your_ip`; HTTP/HTTPS open on security group as in plan.
3. **Build** — Single image philosophy: multi-stage Dockerfile if present; pin tags; avoid baking secrets into layers.
4. **Database & migrations** — If Alembic or migrations exist: backup before migrate; apply with a rollback story. Supabase/Postgres URLs belong in env, not code.
5. **Deploy sequence** — Prefer plan review → apply → smoke test (`/health` or equivalent), verify Nginx → FastAPI routing, spot-check search and chat streaming if applicable.
6. **Post-deploy** — Watch errors and latency briefly; confirm Kafka connectivity if the stack includes it on EC2; LangSmith/traces only if configured — no secret leakage in logs.
7. **Rollback** — Previous Docker tag or Terraform state revert strategy documented before risky changes; document manual steps if automated rollback scripts are absent.

## Examples

- **User:** “We’re ready to ship search fixes to EC2.” → Checklist [references/shopsense-deployment-checklist.md](references/shopsense-deployment-checklist.md); ensure reviewer sign-off on `app/search/`; `terraform plan` then `apply` with `your_ip`; curl health endpoint; tail logs.
- **User:** “First-time Terraform apply for ShopSense.” → Verify AWS credentials, S3 backend in `backend.tf`, key pair exists, AMI/instance vars match region; run plan with explicit `your_ip`; record outputs `public_ip` and SSH command.
- **User:** “Rollback after bad deploy.” → Redeploy previous known-good image/tag; if infra broke, restore from last good Terraform state **only** with understanding of state semantics — do not destroy production blindly.

## References

- [shopsense-deployment-checklist.md](references/shopsense-deployment-checklist.md)
- Terraform and layout: `ShopSense_Platform_Plan_v3.md` §13–14
