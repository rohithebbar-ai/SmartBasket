from fastapi import APIRouter

router = APIRouter()

# Endpoints — implement in Week 3 (Days 12–13):
#   POST /         — streaming chat endpoint (SSE)
#                    Accepts: {message: str, session_id: str}
#                    Returns: Server-Sent Events stream of response tokens
#                    Runs LangGraph graph as a background coroutine; does not block web thread.
