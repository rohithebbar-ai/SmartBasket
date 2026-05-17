from fastapi import APIRouter

from app.schemas.search import AnalyticsResponse

router = APIRouter()

# Endpoints — implement in Week 2 (Day 10, alongside NL-to-SQL):
#   POST /query — admin-only NL-to-SQL endpoint
#                 Auth: requires require_admin dependency (from app.auth.dependencies)
#                 Body: {question: str}
#                 Returns: AnalyticsResponse
#
# Example queries this endpoint handles:
#   "Which brands have the highest average rating?"
#   "Show me products that are out of stock"
#   "What is the average price per category?"
#   "Which products have had the most price changes this week?"
