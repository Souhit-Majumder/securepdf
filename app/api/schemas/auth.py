"""
Pydantic schemas for SecurePDF user authentication and session management.
"""
from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_.-]{3,50}$")


class UserRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=3, max_length=255, description="User email address")
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    password: str = Field(..., min_length=8, max_length=128, description="Password (min 8 chars)")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email address format")
        return v

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if not USERNAME_REGEX.match(v):
            raise ValueError("Username must be 3-50 characters containing letters, numbers, hyphens, dots, or underscores")
        return v


class UserLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(..., min_length=1, max_length=255, description="Email or Username")
    password: str = Field(..., min_length=1, max_length=128, description="Password")

    @field_validator("identifier")
    @classmethod
    def clean_identifier(cls, v: str) -> str:
        return v.strip()


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    email: str
    username: str
    created_at: str


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
