from fastapi import APIRouter

from app.schemas.search import SearchResponse

router = APIRouter()

# Endpoints — implement in Week 2 (Days 8–11):
#   POST /          — main search endpoint; routes to semantic, analytical, or hybrid path
#                     Body: {query: str}
#                     Returns: SearchResponse
#   GET  /suggest   — autocomplete suggestions from product names
