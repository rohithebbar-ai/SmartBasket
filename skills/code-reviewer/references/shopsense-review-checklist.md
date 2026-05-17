# ShopSense review checklist

Use alongside static tools (ruff, bandit, semgrep). Aligns with `ShopSense_Platform_Plan_v3.md`.

## SQL & analytics

- [ ] NL-to-SQL: only **SELECT** (or explicitly allowed statements); reject DDL/DML from generated SQL.
- [ ] Validation layer (sqlparse or equivalent) runs **before** execution; retries bounded.
- [ ] Schema/context passed to the model is minimal (avoid dumping entire DB metadata).
- [ ] Parameterized queries where hand-written SQL exists; no `f"{user_input}"` inside SQL strings.

## Agent & MCP (v3)

- [ ] Tools expose least privilege (e.g. cart/checkout separated from raw catalog admin).
- [ ] Checkout or payment-adjacent steps require explicit human confirmation where designed.
- [ ] Streaming responses do not leak internal prompts or connection strings in logs.

## API & auth

- [ ] JWT validation at Nginx/API boundary as per deployment; short-lived tokens.
- [ ] Rate limiting considered for search/chat/analytics endpoints.
- [ ] Admin NL-to-SQL routes protected differently from public product APIs.

## Kafka & workers

- [ ] Producers handle failures; consumers commit offsets safely; poison messages don’t silent-drop orders or inventory-critical events.
- [ ] Topics and payloads documented; no PII in plaintext event payloads without justification.

## Infrastructure secrets

- [ ] No `GROQ_API_KEY`, `DATABASE_URL`, `QDRANT_*`, `KAFKA_*`, Supabase keys in git.
- [ ] `.env` and Terraform vars documented in runbooks, not duplicated in code.

## Frontend (Vite + TS)

- [ ] No secrets in client bundle; API base URL from env at build time.
- [ ] XSS: sanitize or avoid `dangerouslySetInnerHTML` for model-generated HTML.
