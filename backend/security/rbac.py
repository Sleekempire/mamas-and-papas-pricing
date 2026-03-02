"""
security/rbac.py — Role-Based Access Control FastAPI dependencies.

Roles (highest to lowest privilege):
  Admin        → full access, manage users
  Analyst      → upload data, train models, run optimisation, read recommendations
  Merchandiser → run optimisation (not training), read recommendations
  Viewer       → read recommendations only
"""
from __future__ import annotations

from functools import lru_cache
from typing import Set, Tuple

from fastapi import HTTPException, status, Depends

from security.auth import TokenData, get_current_user

# ── Role hierarchy ────────────────────────────────────────────────────────────
ROLES: Set[str] = {"Admin", "Analyst", "Merchandiser", "Viewer"}

ROLE_HIERARCHY: dict[str, int] = {
    "Admin": 4,
    "Analyst": 3,
    "Merchandiser": 2,
    "Viewer": 1,
}


def require_roles(*allowed_roles: str):
    """
    FastAPI dependency factory.
    Usage: Depends(require_roles("Admin", "Analyst"))
    """
    allowed_set = set(allowed_roles)

    async def _check(current_user: TokenData = Depends(get_current_user)) -> TokenData:
        if current_user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' does not have access to this resource.",
            )
        return current_user

    return _check


def require_min_role(min_role: str):
    """
    FastAPI dependency factory for minimum role level.
    e.g. require_min_role("Analyst") allows Analyst, Admin.
    """
    min_level = ROLE_HIERARCHY.get(min_role, 0)

    async def _check(current_user: TokenData = Depends(get_current_user)) -> TokenData:
        user_level = ROLE_HIERARCHY.get(current_user.role, 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Minimum required role is '{min_role}'.",
            )
        return current_user

    return _check


# ── Pre-built dependencies ─────────────────────────────────────────────────────
RequireAdmin = require_roles("Admin")
RequireAnalystOrAbove = require_min_role("Analyst")
RequireMerchandiserOrAbove = require_min_role("Merchandiser")
RequireAnyRole = require_min_role("Viewer")
