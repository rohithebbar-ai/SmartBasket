---
name: shopsense-coder
description: Implements and refactors ShopSense features — modular FastAPI monolith, LangGraph chat agent, semantic search, NL-to-SQL, Kafka events, workers, Vite React storefront, Terraform on AWS. Use when writing new code, extending modules, or aligning implementation with ShopSense_Platform_Plan_v3.md.
---

# ShopSense — Coder

Use this skill when **building or changing** ShopSense application code or adjacent tooling. Pair with `shopsense-code-reviewer` before merge and `shopsense-deployment-agent` when releasing.

## Instructions

1. **Anchor on the plan** — Read relevant sections of `ShopSense_Platform_Plan_v3.md` (modules, NL-to-SQL, agent flow, Kafka, schema, repo layout §13, Terraform §14). Do not invent parallel architectures (e.g. splitting into microservices) unless the plan explicitly discusses extraction criteria.
2. **Respect module boundaries** — Place code in `app/<module>/` with `router.py`, `models.py`, `schemas.py`, `service.py` as appropriate; shared DB/session/settings stay in `app/database.py`, `app/config.py`. LangGraph graphs, nodes, and prompts stay under `app/agent/`.
3. **Keep the web stack responsive** — Long-running LangGraph work belongs off the hot path (worker process / async patterns per plan). Avoid blocking calls in FastAPI handlers where streaming or background workers are specified.
4. **NL-to-SQL and retrieval** — Generated SQL must pass validation (intent: read-only where required), bounded retries, and minimal schema context to the model. Combine vector + SQL only through the hybrid/search layers described in the plan, not ad hoc string execution.
5. **Events and caching** — Kafka producers/consumers: clear topic semantics, safe offset handling, and no silent drops for order- or inventory-critical paths. Redis keys need TTLs and naming discipline where demand counters or sessions are involved.
6. **Frontend** — Vite + TypeScript: environment-based API base URL, no secrets in the bundle, cautious rendering of model-generated content (avoid unsafe HTML injection).
7. **Infra touchpoints** — Terraform under `infra/terraform/`; Nginx config under `infra/nginx/`. Prefer `terraform plan` before apply; document new variables and outputs.
8. **Testing** — Add or update tests under `tests/` for behavior you change (especially NL-to-SQL validation, query router, and Kafka-related logic).

## Examples

- **Feature:** “Add an admin endpoint for analytics NL-to-SQL.” → Implement under `app/analytics/`, protect differently from public routes, reuse validation patterns from `app/search/nl_to_sql.py`, add `tests/test_nl_to_sql.py` cases.
- **Feature:** “New LangGraph node for hybrid retrieval.” → Add under `app/agent/nodes/`, wire in `graph.py`, update `state.py` and prompts; ensure tools do not bypass checkout human-in-the-loop rules from §19.
- **Bugfix:** “Kafka consumer double-processes messages.” → Inspect commit strategy and idempotency keys in the relevant consumer; align with event schema in the plan.

## References

- Canonical spec: [`ShopSense_Platform_Plan_v3.md`](../../ShopSense_Platform_Plan_v3.md) (repo root)
- Review gate: [`code-reviewer`](../code-reviewer/SKILL.md)
