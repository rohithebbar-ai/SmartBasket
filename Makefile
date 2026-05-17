.PHONY: dev stop logs test test-module lint format typecheck workers deploy clean install \
        db-push db-new db-reset db-start db-stop

# ── Local dev ─────────────────────────────────────────────────────────────────

install:
	uv sync --extra dev

dev:
	docker compose up -d
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

stop:
	docker compose down

logs:
	docker compose logs -f

workers:
	uv run python workers/run_workers.py

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	uv run pytest tests/ -v --cov=app --cov-report=term-missing

# Run tests for a single module: make test-module module=search
test-module:
	uv run pytest tests/$(module)/ -v

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	uv run ruff check app/ workers/ tests/

format:
	uv run ruff format app/ workers/ tests/

typecheck:
	uv run mypy app/

# ── Data pipeline (run in order) ─────────────────────────────────────────────

ingest:
	uv run python data/ingestion/fetch_bestbuy.py
	uv run python data/ingestion/process_kaggle.py
	uv run python data/ingestion/seed_postgres.py
	uv run python data/ingestion/run_sentiment.py
	uv run python data/ingestion/generate_embeddings.py
	uv run python data/ingestion/verify_ingestion.py

# ── Database migrations (Supabase CLI) ───────────────────────────────────────
# Requires: supabase link --project-ref <ref>  (one-time per machine)
# Local push:  make db-push DB_URL=postgresql://shopsense:shopsense@localhost:5432/shopsense
# Remote push: make db-push  (uses linked project)

db-push:
ifdef DB_URL
	supabase db push --db-url "$(DB_URL)"
else
	supabase db push
endif

# make db-new name=add_product_views
db-new:
	supabase migration new $(name)

db-reset:
	supabase db reset

db-start:
	supabase start

db-stop:
	supabase stop

# ── Infrastructure ────────────────────────────────────────────────────────────

# Usage: make deploy YOUR_IP=1.2.3.4
deploy:
	cd infra/terraform && terraform apply -var="your_ip=$(YOUR_IP)"

tf-plan:
	cd infra/terraform && terraform plan -var="your_ip=$(YOUR_IP)"

tf-destroy:
	cd infra/terraform && terraform destroy -var="your_ip=$(YOUR_IP)"

tf-init:
	cd infra/terraform && terraform init

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
