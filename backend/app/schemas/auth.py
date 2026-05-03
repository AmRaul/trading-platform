from pydantic import BaseModel, Field, field_validator
from typing import Optional
import re


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class UserCreate(BaseModel):
    """
    User registration schema with strong password validation.

    Password requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    - Maximum 72 bytes (bcrypt limitation)
    """
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Username (3-50 characters)"
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=72,
        description="Strong password (8-72 characters)"
    )

    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate username format"""
        v = v.strip()

        if not v:
            raise ValueError('Username cannot be empty')

        # Alphanumeric and underscores only
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('Username can only contain letters, numbers, and underscores')

        return v

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Enforce strong password requirements"""

        # Check byte length (bcrypt limit)
        if len(v.encode('utf-8')) > 72:
            raise ValueError('Password cannot exceed 72 bytes')

        # Minimum length already checked by Field(min_length=8)

        # Must contain uppercase letter
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')

        # Must contain lowercase letter
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')

        # Must contain digit
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')

        # Check for common weak patterns
        weak_patterns = [
            r'password',
            r'12345',
            r'qwerty',
            r'admin',
            r'letmein',
            r'welcome'
        ]

        for pattern in weak_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError(f'Password contains weak pattern: {pattern}')

        return v


class UserLogin(BaseModel):
    username: str
    password: str = Field(..., max_length=72)
