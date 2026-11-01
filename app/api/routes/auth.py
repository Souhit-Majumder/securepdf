"""
Authentication and session management routes for SecurePDF users.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.dependencies import (
    get_repository,
    get_current_user_from_session,
    SESSION_COOKIE_NAME,
)
from app.api.schemas.auth import (
    MessageResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.crypto.auth import (
    SESSION_COOKIE_MAX_AGE,
    calculate_session_expiry,
    generate_session_token,
    hash_password,
    is_session_expired,
    verify_password,
)
from app.database.models import User
from app.database.repository import Repository

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegisterRequest,
    request: Request,
    response: Response,
    repo: Repository = Depends(get_repository),
):
    """
    Register a new user account.
    Requires email, username, and password.
    Hashes password using hashlib.scrypt with a unique salt.
    Establishes an authenticated session via HttpOnly cookie.
    """
    # Check for existing email
    if repo.get_user_by_email(payload.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists."
        )

    # Check for existing username
    if repo.get_user_by_username(payload.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This username is already taken. Please choose another."
        )

    # Hash password with scrypt
    password_hash, salt = hash_password(payload.password)

    # Create user
    user = repo.create_user(
        email=payload.email,
        username=payload.username,
        password_hash=password_hash,
        salt=salt,
    )

    # Establish session
    session_token = generate_session_token()
    expires_at = calculate_session_expiry()
    repo.create_session(session_token=session_token, user_id=user.id, expires_at=expires_at)

    # Set secure HttpOnly cookie
    is_secure = request.url.scheme == "https"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )

    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        created_at=str(user.created_at),
    )


@router.post("/login", response_model=UserResponse)
def login(
    payload: UserLoginRequest,
    request: Request,
    response: Response,
    repo: Repository = Depends(get_repository),
):
    """
    Authenticate user by email or username and password.
    Establishes an authenticated session via HttpOnly cookie.
    """
    identifier = payload.identifier.strip()
    user = None

    if "@" in identifier:
        user = repo.get_user_by_email(identifier)
    else:
        user = repo.get_user_by_username(identifier)
        if not user:
            # Fallback in case user typed email without @ or username match failed
            user = repo.get_user_by_email(identifier)

    # Perform timing-safe password verification
    if not user:
        # Dummy scrypt to prevent timing analysis on non-existent accounts
        verify_password("dummy_password_timing_pad", "0" * 128, "0" * 32)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password."
        )

    if not verify_password(payload.password, user.password_hash, user.salt):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password."
        )

    # Create new session
    session_token = generate_session_token()
    expires_at = calculate_session_expiry()
    repo.create_session(session_token=session_token, user_id=user.id, expires_at=expires_at)

    # Set secure HttpOnly cookie
    is_secure = request.url.scheme == "https"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )

    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        created_at=str(user.created_at),
    )


@router.get("/me", response_model=UserResponse)
def get_current_user(current_user: User = Depends(get_current_user_from_session)):
    """Retrieve the currently authenticated user's profile from the session."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        created_at=str(current_user.created_at),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    repo: Repository = Depends(get_repository),
):
    """
    Terminate the server session and clear the session cookie.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        repo.delete_session(token)

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return MessageResponse(message="Successfully logged out.")
