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

_BRAND_BOOST     = 0.15
_CATEGORY_BOOST  = 0.03
_PRICE_FIT_BOOST = 0.05
_FEATURE_BOOST   = 0.03
_COLOUR_BOOST    = 0.08   # fashion: preferred colour match in attributes
_OCCASION_BOOST  = 0.10   # fashion: occasion matches session occasion_context
_COMFORT_BOOST   = 0.06   # fashion: high comfort_sentiment when comfort_priority set
_SENTIMENT_THRESHOLD = 4.0


def _get_product_colour(r: dict) -> str:
    """Extract normalised colour from product attributes dict."""
    attrs = r.get("attributes") or {}
    return str(attrs.get("colour") or "").lower()


async def personalise(state: ShopSenseState) -> dict:
    results: list[dict] = state.get("search_results", [])
    prefs: dict = state.get("user_preferences", {})

    if not results or not prefs:
        return {}

    preferred_brands = {b.lower() for b in (prefs.get("preferred_brands") or [])}
    preferred_categories = {c.lower() for c in (prefs.get("preferred_categories") or [])}
    price_min = prefs.get("typical_price_min")
    price_max = prefs.get("typical_price_max")

    # Fashion-specific preference signals
    preferred_colours = {c.lower() for c in (prefs.get("preferred_colours") or [])}
    preferred_occasions = {o.lower() for o in (prefs.get("preferred_occasions") or [])}
    comfort_priority: bool = bool(prefs.get("comfort_priority"))
    # occasion_context carries what the user is shopping for this session
    session_occasion = (state.get("occasion_context") or "").lower()

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

        # Fashion: preferred colour match
        if preferred_colours:
            product_colour = _get_product_colour(r)
            if product_colour and any(c in product_colour for c in preferred_colours):
                boost += _COLOUR_BOOST

        # Fashion: occasion match — both stored prefs and the current session occasion
        attrs = r.get("attributes") or {}
        product_occasion = str(attrs.get("occasion") or "").lower()
        if product_occasion:
            if preferred_occasions and any(o in product_occasion for o in preferred_occasions):
                boost += _OCCASION_BOOST
            elif session_occasion and session_occasion in product_occasion:
                boost += _OCCASION_BOOST

        # Fashion: comfort priority — boost high-comfort-sentiment products
        if comfort_priority:
            sentiment_scores: dict = r.get("sentiment_scores") or {}
            if sentiment_scores.get("comfort_sentiment", 0.0) >= _SENTIMENT_THRESHOLD:
                boost += _COMFORT_BOOST

        # Electronics / generic: feature sentiment boosts
        if feature_names:
            sentiment_scores = r.get("sentiment_scores") or {}
            for feature in feature_names:
                score = sentiment_scores.get(f"{feature}_sentiment", 0.0)
                if score >= _SENTIMENT_THRESHOLD:
                    boost += _FEATURE_BOOST

        if boost:
            r["relevance_score"] = r.get("relevance_score", 0.0) + boost

    results.sort(key=lambda r: r.get("relevance_score", 0.0), reverse=True)
    return {"search_results": results}
