"""
api/routers/auth.py — Authentication endpoints.
POST /token — login with email/password, return JWT
POST /refresh — exchange refresh token for new access token
GET /me — return current user info
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import User
from security.auth import (
    create_access_token, create_refresh_token,
    decode_token, get_current_user, verify_password, TokenData,
)
from security.audit import AuditEventType, write_audit_log

router = APIRouter()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_in: int


class UserProfile(BaseModel):
    user_id: str
    email: str
    role: str


@router.post("/token", response_model=TokenResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    user = db.query(User).filter(User.email == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        write_audit_log(db, AuditEventType.LOGIN_FAILURE, None, None,
                        "/api/v1/auth/token", {"email": form_data.username[:50]}, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    access_token = create_access_token(user.id, user.role, user.email)
    write_audit_log(db, AuditEventType.LOGIN, user.id, user.role,
                    "/api/v1/auth/token", {}, ip)

    from config import settings
    return TokenResponse(
        access_token=access_token,
        role=user.role,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserProfile)
async def get_me(current_user: TokenData = Depends(get_current_user)):
    return UserProfile(
        user_id=current_user.user_id,
        email=current_user.email,
        role=current_user.role,
    )
