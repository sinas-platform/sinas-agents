"""Authentication schemas."""
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict
from datetime import datetime
import uuid


class LoginRequest(BaseModel):
    email: EmailStr


class LoginResponse(BaseModel):
    message: str
    session_id: uuid.UUID


class OTPVerifyRequest(BaseModel):
    session_id: uuid.UUID
    otp_code: str


class OTPVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreate(BaseModel):
    name: str
    permissions: Dict[str, bool]
    expires_at: Optional[datetime] = None


class APIKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    permissions: Dict[str, bool]
    is_active: bool
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreatedResponse(APIKeyResponse):
    api_key: str  # Only returned once upon creation


class CreateUserRequest(BaseModel):
    email: EmailStr
