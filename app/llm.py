"""
Central LLM gateway — single point for all LLM calls.

Set LLM_PROVIDER in .env:
  LLM_PROVIDER=bedrock  → AWS Bedrock Claude (prod, Claude Sonnet / Haiku)
  LLM_PROVIDER=groq     → Groq API / LLaMA (dev, default)
  LLM_PROVIDER=gemini   → Google Gemini API (dev alt)
  LLM_PROVIDER=mock     → canned responses (CI / no-key envs)

Two tiers map to different models per provider:
  fast        → classification, routing, NL-to-SQL, filter extraction
  generation  → response synthesis, insight generation, comparison

Model defaults per provider (all overridable in .env):
  Bedrock  fast=claude-haiku-4-5  generation=claude-sonnet-4-5
  Groq     fast=llama-3.1-8b-instant  generation=llama-3.3-70b-versatile
  Gemini   fast=gemini-2.5-flash-lite  generation=gemini-2.5-flash

Usage:
    from app.llm import call_llm

    text = await call_llm("Your prompt here", tier="fast", max_tokens=150)
"""

import asyncio
import logging
from typing import Literal

from app.config import settings

log = logging.getLogger(__name__)

# ── Client singletons (lazy — only the active provider is ever initialised) ───

_bedrock_client = None
_groq_client = None
_gemini_client = None


def _get_bedrock():
    global _bedrock_client
    if _bedrock_client is None:
        import boto3
        if settings.aws_profile:
            session = boto3.Session(profile_name=settings.aws_profile)
            _bedrock_client = session.client("bedrock-runtime", region_name=settings.aws_region)
        else:
            kwargs: dict = {"region_name": settings.aws_region}
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                kwargs["aws_access_key_id"] = settings.aws_access_key_id
                kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
            _bedrock_client = boto3.client("bedrock-runtime", **kwargs)
    return _bedrock_client


def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import AsyncGroq
        _groq_client = AsyncGroq(api_key=settings.groq_key)
    return _groq_client


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=settings.gemini_key)
    return _gemini_client


# ── Shared utility ─────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    """Strip markdown code fences that some models add despite instructions."""
    if not text.startswith("```"):
        return text
    first_newline = text.find("\n")
    if first_newline == -1:
        return text
    text = text[first_newline + 1:]
    text = text.rsplit("```", 1)[0]
    return text.strip()


# ── Provider implementations ──────────────────────────────────────────────────

def _call_bedrock_sync(prompt: str, model_id: str, max_tokens: int, temperature: float) -> str:
    response = _get_bedrock().converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    raw = response["output"]["message"]["content"][0]["text"].strip()
    return _strip_fences(raw)


async def _call_bedrock(prompt: str, tier: str, max_tokens: int, temperature: float) -> str:
    model_id = (
        settings.bedrock_fast_model_id if tier == "fast"
        else settings.bedrock_generation_model_id
    )
    return await asyncio.to_thread(
        _call_bedrock_sync, prompt, model_id, max_tokens, temperature
    )


async def _call_groq(prompt: str, tier: str, max_tokens: int, temperature: float) -> str:
    model = settings.groq_fast_model if tier == "fast" else settings.groq_generation_model
    response = await _get_groq().chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return _strip_fences(response.choices[0].message.content.strip())


async def _call_gemini(prompt: str, tier: str, max_tokens: int, temperature: float) -> str:
    from google.genai import types as genai_types
    model = settings.gemini_fast_model if tier == "fast" else settings.gemini_generation_model
    client = _get_gemini()
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        ),
    )
    return _strip_fences(response.text.strip())


def _call_mock(prompt: str, tier: str) -> str:
    """Canned responses — used when LLM_PROVIDER=mock or APP_ENV=testing.

    Detection order: check for the most specific keyword first so each schema
    gets its own valid canned response. Callers parse these into Pydantic models,
    so the JSON shapes must match exactly.
    """
    if tier == "generation":
        return "The query results show strong product performance with high customer satisfaction."
    p = prompt.lower()
    # NL-to-SQL / hybrid SQL prompts
    if any(kw in p for kw in ("return sql only", "select queries only", "select that:")):
        return (
            "SELECT id, name, brand, category, current_price, avg_rating, stock_count "
            "FROM products WHERE is_active = true ORDER BY avg_rating DESC LIMIT 10"
        )
    # ConfirmationOutput
    if "confirm" in p and "decline" in p and "ambiguous" in p:
        return '{"decision": "CONFIRM", "reasoning": "mock confirmation"}'
    # IntentOutput — intent classifier prompt contains all 10 intent names
    if "product_search" in p and "out_of_scope" in p:
        return '{"intent": "PRODUCT_SEARCH", "reasoning": "mock intent"}'
    # Constraint extractor — extract the original query from "Query: ..." at the end of prompt
    if "available filters" in p and "rewritten_query" in p:
        import re as _re
        m = _re.search(r"query:\s*(.+)$", prompt.strip(), _re.IGNORECASE | _re.MULTILINE)
        raw_q = m.group(1).strip() if m else "product search"
        return (
            f'{{"rewritten_query": {raw_q!r}, "price_value": null, "price_currency": null, '
            f'"price_type": null}}'
        )
    # FilterExtractionOutput (old agent path)
    if "rewritten_query" in p or "filter extraction" in p:
        return '{"rewritten_query": "gaming laptop", "max_price": null, "min_price": null, "brand": null, "category": null, "use_case": null, "features": []}'
    # QueryRouterOutput / QueryTypeRouterOutput (default fast-tier fallback)
    return '{"type": "SEMANTIC", "reasoning": "mock routing"}'


# ── Public interface ──────────────────────────────────────────────────────────

async def call_llm(
    prompt: str,
    tier: Literal["fast", "generation"] = "fast",
    max_tokens: int = 500,
    temperature: float = 0.0,
) -> str:
    """
    Single entry point for all LLM calls. Returns raw response text.

    Args:
        prompt:      Full prompt string.
        tier:        "fast" (routing/SQL) or "generation" (synthesis/insight).
        max_tokens:  Maximum output tokens.
        temperature: 0.0 = deterministic, higher = more creative.

    Returns:
        Response text with markdown fences stripped.

    Raises:
        Exception from the underlying provider on network/auth failure.
        Callers handle retries as needed.
    """
    provider = settings.llm_provider.value

    # Always mock when running under pytest — prevents accidental API calls in CI
    if settings.is_testing or provider == "mock":
        return _call_mock(prompt, tier)

    log.debug("call_llm provider=%s tier=%s max_tokens=%d", provider, tier, max_tokens)

    if provider == "bedrock":
        return await _call_bedrock(prompt, tier, max_tokens, temperature)

    if provider == "groq":
        if not settings.groq_key:
            raise ValueError("LLM_PROVIDER=groq but GROQ_KEY is not set in .env")
        return await _call_groq(prompt, tier, max_tokens, temperature)

    if provider == "gemini":
        if not settings.gemini_key:
            raise ValueError("LLM_PROVIDER=gemini but GEMINI_KEY is not set in .env")
        return await _call_gemini(prompt, tier, max_tokens, temperature)

    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider!r}. Valid options: bedrock | groq | gemini | mock"
    )
