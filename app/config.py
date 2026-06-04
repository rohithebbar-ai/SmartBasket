from enum import Enum
from functools import lru_cache

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_KEY = "changeme-generate-with-openssl-rand-hex-32"


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class EmbeddingProvider(str, Enum):
    JINA = "JINA"
    NVIDIA = "NVIDIA"


class LLMProvider(str, Enum):
    BEDROCK = "bedrock"
    GROQ = "groq"
    GEMINI = "gemini"
    MOCK = "mock"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_env: AppEnv = AppEnv.DEVELOPMENT
    app_secret_key: str = Field(
        default=_INSECURE_DEFAULT_KEY,
        min_length=32,
        description="JWT signing key. Generate: openssl rand -hex 32",
    )
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = Field(default=24, gt=0)

    # ── Database ──────────────────────────────────────────────────────────────
    # SQLAlchemy connects here for querying only.
    # Schema is managed by Supabase CLI migrations — never call create_all().
    database_url: str = "postgresql+asyncpg://shopsense:shopsense@localhost:5432/shopsense"
    test_database_url: str = "postgresql+asyncpg://shopsense_test:shopsense_test@localhost:5433/shopsense_test"

    # Supabase project reference (CLI + SDK; not required for pure SQLAlchemy usage)
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None  # None for local Docker; set for Qdrant Cloud
    qdrant_collection_name: str = "products"

    # ── Kafka ─────────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_consumer_group_id: str = "shopsense-consumer-group"
    kafka_auto_offset_reset: str = "earliest"

    # Topic names — all producers/consumers read from here; never hardcode strings
    kafka_topic_product_viewed: str = "product.viewed"
    kafka_topic_product_created: str = "product.created"
    kafka_topic_cart_updated: str = "cart.updated"
    kafka_topic_order_created: str = "order.created"
    kafka_topic_order_delivered: str = "order.delivered"
    kafka_topic_price_updated: str = "price.updated"

    # ── LLM Provider ─────────────────────────────────────────────────────────
    # Switch LLM_PROVIDER in .env — no code change needed.
    # bedrock = prod (Claude); groq = dev default; gemini = dev alt; mock = CI
    llm_provider: LLMProvider = LLMProvider.GROQ

    # Groq (dev default) — https://console.groq.com/keys
    groq_key: str | None = None
    groq_fast_model: str = "llama-3.1-8b-instant"
    groq_generation_model: str = "llama-3.3-70b-versatile"

    # Gemini (dev alt) — https://aistudio.google.com/apikey
    gemini_key: str | None = None
    gemini_fast_model: str = "gemini-2.5-flash-lite"
    gemini_generation_model: str = "gemini-2.5-flash"

    # ── AWS / Bedrock ─────────────────────────────────────────────────────────
    # Auth priority: instance role → aws_profile → explicit keys.
    # Never set explicit keys in production — use the instance role instead.
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # Slow, high-quality: response synthesis, aspect sentiment, comparison
    bedrock_generation_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    # Fast, cheap: intent classification, query routing, NL-to-SQL, filter extraction
    bedrock_fast_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"

    # ── Embeddings ────────────────────────────────────────────────────────────
    # Switch provider by changing EMBEDDING_PROVIDER in .env — no code change needed.
    # Switching after ingestion requires recreating the Qdrant collection.
    embedding_provider: EmbeddingProvider = EmbeddingProvider.JINA
    embedding_dimensions: int = Field(default=1024, gt=0)

    jina_api_key: str | None = None
    jina_model: str = "jina-embeddings-v3"

    nvidia_api_key: str | None = None
    nvidia_model: str = "nvidia/nv-embedqa-e5-v5"

    # ── Frontend ──────────────────────────────────────────────────────────────
    # Set to your Vercel URL in production (e.g. https://shopsense.vercel.app).
    # Localhost is always allowed for dev — this adds a second allowed origin.
    frontend_url: str | None = None

    # ── MCP Server ────────────────────────────────────────────────────────────
    # MCP tools are mounted inside the main FastAPI app at /mcp — no separate
    # process or port. mcp_server_url points to the main app's /mcp prefix.
    mcp_server_url: str = "http://localhost:8000/mcp"

    # ── External Services ─────────────────────────────────────────────────────
    sendgrid_api_key: str | None = None
    sendgrid_from_email: str = "noreply@shopsense.com"

    # Gmail SMTP fallback — used when sendgrid_api_key is not set.
    # Requires a Gmail App Password (not your regular password).
    # Enable at: myaccount.google.com/apppasswords
    gmail_user: str | None = None        # e.g. you@gmail.com
    gmail_app_password: str | None = None  # 16-char app password

    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    tavily_api_key: str | None = None

    # ── Observability ─────────────────────────────────────────────────────────
    langchain_tracing_v2: bool = True
    langchain_api_key: str | None = None
    langchain_project: str = "shopsense"

    # ── Pricing Engine ────────────────────────────────────────────────────────
    pricing_engine_interval_seconds: int = Field(default=120, gt=0)
    pricing_demand_threshold: int = Field(default=50, gt=0)
    pricing_max_multiplier: float = Field(default=1.30, gt=1.0, le=2.0)
    pricing_min_multiplier: float = Field(default=0.80, gt=0.0, lt=1.0)

    # ── CLIP Visual Search Microservice ──────────────────────────────────────
    # Local dev: http://clip-service:8001  (docker-compose internal network)
    # Production: https://<hf-username>-clip-service.hf.space  (HF Spaces)
    clip_service_url: str = "http://clip-service:8001"
    clip_service_api_key: str = ""  # shared secret; set in both .env and HF Space secrets

    # ── Data Ingestion ────────────────────────────────────────────────────────
    bestbuy_api_key: str | None = None

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("app_secret_key")
    @classmethod
    def secret_key_not_insecure_default(cls, v: str) -> str:
        if v == _INSECURE_DEFAULT_KEY:
            # Allowed in dev/test; blocked in production by model_validator below
            return v
        if len(v) < 32:
            raise ValueError("app_secret_key must be at least 32 characters")
        return v

    @model_validator(mode="after")
    def production_guards(self) -> "Settings":
        if self.app_env == AppEnv.PRODUCTION:
            if self.app_secret_key == _INSECURE_DEFAULT_KEY:
                raise ValueError(
                    "APP_SECRET_KEY must be set to a secure value in production. "
                    "Generate one with: openssl rand -hex 32"
                )
            if self.embedding_provider == EmbeddingProvider.JINA and not self.jina_api_key:
                raise ValueError("JINA_API_KEY must be set when EMBEDDING_PROVIDER=JINA")
            if self.embedding_provider == EmbeddingProvider.NVIDIA and not self.nvidia_api_key:
                raise ValueError("NVIDIA_API_KEY must be set when EMBEDDING_PROVIDER=NVIDIA")
        return self

    # ── Computed helpers ──────────────────────────────────────────────────────
    # Use these instead of comparing app_env strings in application code.

    @computed_field  # type: ignore[misc]
    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnv.PRODUCTION

    @computed_field  # type: ignore[misc]
    @property
    def is_development(self) -> bool:
        return self.app_env == AppEnv.DEVELOPMENT

    @computed_field  # type: ignore[misc]
    @property
    def is_testing(self) -> bool:
        return self.app_env == AppEnv.TESTING

    @computed_field  # type: ignore[misc]
    @property
    def active_database_url(self) -> str:
        """Returns test_database_url when running under pytest, database_url otherwise."""
        return self.test_database_url if self.is_testing else self.database_url

    @computed_field  # type: ignore[misc]
    @property
    def kafka_bootstrap_servers_list(self) -> list[str]:
        """Splits comma-separated broker string for multi-broker Kafka configs."""
        return [s.strip() for s in self.kafka_bootstrap_servers.split(",")]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Module-level singleton — import this everywhere.
# Never import os.environ directly; add a field here instead.
settings: Settings = get_settings()
