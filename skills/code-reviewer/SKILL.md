---
name: shopsense-code-reviewer
description: Security and quality review for the ShopSense AI commerce codebase — FastAPI modular monolith, LangGraph agent, NL-to-SQL, Kafka, Qdrant, Redis, Groq, Vite storefront. Use when reviewing PRs, auditing agent or SQL-generation paths, or before deploy for this repository.
---

# ShopSense — Code reviewer

Architecture context lives in [`ShopSense_Platform_Plan_v3.md`](../../ShopSense_Platform_Plan_v3.md) (repository root: parent of `skills/`). This skill biases reviews toward that design — module boundaries, event flows, and AI safety surfaces.

## Instructions

1. **Confirm scope** — Single file, one module under `app/` (`products`, `orders`, `users`, `search`, `agent`, `analytics`), `workers/`, `frontend/`, or `infra/`.
2. **Prioritize risks** — (a) SQL injection and unsafe NL-to-SQL execution, (b) prompt injection and tool/MCP boundaries, (c) secrets and JWT/session handling, (d) Kafka consumer correctness and idempotency, (e) blocking work on the FastAPI request path.
3. **Run tooling when available** — From this skill directory: `./scripts/review.py <path>` for full review; `./scripts/review.py <path> --security-only` before merges touching auth, generated SQL, or agent tools; `./scripts/security-check.py <path>` for a fast security pass. If `bandit`, `ruff`, or `semgrep` are missing, perform a manual pass using [references/shopsense-review-checklist.md](references/shopsense-review-checklist.md).
4. **Classify findings** — CRITICAL (exploit or data loss), HIGH, MEDIUM, LOW. Tie recommendations to the platform plan where helpful (e.g. NL-to-SQL validate-and-retry, Section 5).
5. **Report** — Short severity counts, then grouped issues with `file:line`, concrete fix direction, and no raw secrets in the output.

## Examples

- **User:** “Review `app/search/nl_to_sql.py` before we merge.” → Run `./scripts/review.py app/search/nl_to_sql.py`; emphasize SELECT-only policy, validation before execute, and no string concatenation of user text into SQL.
- **User:** “Security scan for the agent module.” → `./scripts/review.py app/agent/ --security-only` plus checklist sections Agent & MCP and API & auth.
- **User:** “Quick secret check on changed files.” → `./scripts/security-check.py path/to/file.py`.

## References

- [shopsense-review-checklist.md](references/shopsense-review-checklist.md)
