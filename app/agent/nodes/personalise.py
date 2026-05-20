"""
personalise — re-ranks search_results by the user's stored preference profile.

No LLM call. Applies additive score boosts to products that match the user's
preferred brands, preferred categories, typical price range, and feature priorities,
then re-sorts descending by the boosted relevance_score.

state.search_results entries are dicts (not ProductResult objects) because the
LangGraph JSON checkpointer requires plain serialisable types. Scores are mutated
in-place on the dicts; objects are never replaced.

feature_priorities from user_preferences is a dict keyed by feature name
(e.g. {"battery": 0.8, "display": 0.5}). Sentiment scores live inside each
product dict under the "sentiment_scores" sub-dict, keyed as "{feature}_sentiment".
A product gets a boost for each priority feature whose sentiment score is >= 4.0.

Reads:  state.search_results (list[dict]), state.user_preferences
Writes: state.search_results (list[dict], re-sorted by boosted relevance_score)

Outgoing edge: → synthesise
"""

import logging

from app.agent.state import ShopSenseState

log = logging.getLogger(__name__)

_BRAND_BOOST    = 0.15
_CATEGORY_BOOST = 0.03
_PRICE_FIT_BOOST = 0.05
_FEATURE_BOOST  = 0.03
_SENTIMENT_THRESHOLD = 4.0


async def personalise(state: ShopSenseState) -> dict:
    results: list[dict] = state.get("search_results", [])
    prefs: dict = state.get("user_preferences", {})

    if not results or not prefs:
        return {}

    preferred_brands = {b.lower() for b in (prefs.get("preferred_brands") or [])}
    preferred_categories = {c.lower() for c in (prefs.get("preferred_categories") or [])}
    price_min = prefs.get("typical_price_min")
    price_max = prefs.get("typical_price_max")

    # feature_priorities is a dict {feature_name: weight} or a list [feature_name, ...]
    raw_priorities = prefs.get("feature_priorities") or {}
    if isinstance(raw_priorities, dict):
        feature_names = list(raw_priorities.keys())
    elif isinstance(raw_priorities, list):
        feature_names = [str(f) for f in raw_priorities]
    else:
        feature_names = []

    for r in results:
        boost = 0.0

        if preferred_brands and r.get("brand", "").lower() in preferred_brands:
            boost += _BRAND_BOOST

        if preferred_categories and r.get("category", "").lower() in preferred_categories:
            boost += _CATEGORY_BOOST

        if price_min is not None and price_max is not None:
            price = r.get("current_price", 0.0)
            if price_min <= price <= price_max:
                boost += _PRICE_FIT_BOOST

        if feature_names:
            sentiment_scores: dict = r.get("sentiment_scores") or {}
            for feature in feature_names:
                score = sentiment_scores.get(f"{feature}_sentiment", 0.0)
                if score >= _SENTIMENT_THRESHOLD:
                    boost += _FEATURE_BOOST

        if boost:
            r["relevance_score"] = r.get("relevance_score", 0.0) + boost

    results.sort(key=lambda r: r.get("relevance_score", 0.0), reverse=True)
    return {"search_results": results}
