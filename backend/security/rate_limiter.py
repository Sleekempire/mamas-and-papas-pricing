"""
security/rate_limiter.py — Per-user rate limiting using SlowAPI.

Different limits are applied per role, extracted from JWT claims.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from config import settings


def _get_user_key(request) -> str:
    """
    Rate-limit key: user_id from JWT claim (extracted by middleware),
    falling back to remote IP for unauthenticated requests.
    """
    # The auth middleware sets request.state.user_id
    user_id = getattr(getattr(request, "state", None), "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


def _get_role_key(request) -> str:
    """Rate-limit key incorporating role for differentiated limits."""
    role = getattr(getattr(request, "state", None), "role", "anonymous")
    user_id = getattr(getattr(request, "state", None), "user_id", None)
    prefix = f"user:{user_id}" if user_id else f"ip:{get_remote_address(request)}"
    return f"{prefix}:role:{role}"


# Global Limiter instance — registered on the FastAPI app
limiter = Limiter(key_func=_get_user_key)


def get_rate_limit_for_role(role: str) -> str:
    """Return the configured rate limit string for a given role."""
    mapping = {
        "Admin": settings.RATE_LIMIT_ADMIN,
        "Analyst": settings.RATE_LIMIT_ANALYST,
        "Merchandiser": settings.RATE_LIMIT_MERCHANDISER,
        "Viewer": settings.RATE_LIMIT_VIEWER,
    }
    return mapping.get(role, "20/minute")
