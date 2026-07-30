"""认证相关 Schema"""
from typing import Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=255)
    role: str = Field(..., pattern="^(ADMIN|TEACHER|STUDENT)$")


class LoginResponse(BaseModel):
    """登录响应"""
    token: str
    username: str
    display_name: Optional[str] = None
    role: str
    redirect_url: str
    expires_in: int = 86400000


class RegisterRequest(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=255)
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: str = Field(..., pattern="^(ADMIN|TEACHER|STUDENT)$")


class UserResponse(BaseModel):
    """用户信息"""
    id: int
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: str
    enabled: bool
    last_login: Optional[str] = None
    created_at: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    """找回密码请求"""
    username: str
    email: Optional[str] = None
    role: str = Field(..., pattern="^(ADMIN|TEACHER|STUDENT)$")
    new_password: str = Field(..., min_length=6, max_length=255)


class ProfileResponse(BaseModel):
    """个人信息"""
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: str


class ProfileUpdateRequest(BaseModel):
    """个人信息更新请求"""
    display_name: Optional[str] = None
    email: Optional[str] = None
    new_password: Optional[str] = None
