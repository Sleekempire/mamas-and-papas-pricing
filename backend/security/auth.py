"""
security/auth.py — JWT token creation, verification, and user extraction.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from config import settings

# ── Password hashing ──────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── OAuth2 bearer scheme ──────────────────────────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


class TokenData:
    def __init__(self, user_id: str, role: str, email: str):
        self.user_id = user_id
        self.role = role
        self.email = email


def hash_password(plain: str) -> str:
    # bcrypt limits to 72 bytes
    truncated = plain.encode('utf-8')[:72].decode('utf-8', 'ignore')
    return pwd_context.hash(truncated)


def verify_password(plain: str, hashed: str) -> bool:
    truncated = plain.encode('utf-8')[:72].decode('utf-8', 'ignore')
    try:
        return pwd_context.verify(truncated, hashed)
    except Exception:
        return False



def create_access_token(user_id: str, role: str, email: str) -> str:
    """Create a short-lived JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived JWT refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        raise CREDENTIALS_EXCEPTION


async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    """FastAPI dependency: extract current user from JWT bearer token."""
    payload = decode_token(token)
    user_id: Optional[str] = payload.get("sub")
    role: Optional[str] = payload.get("role")
    email: Optional[str] = payload.get("email")
    tok_type: Optional[str] = payload.get("type")

    if not user_id or not role or tok_type != "access":
        raise CREDENTIALS_EXCEPTION

    return TokenData(user_id=user_id, role=role, email=email or "")
