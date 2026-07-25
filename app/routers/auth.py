"""认证路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.models import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    RegisterRequest,
    UserResponse,
)
from app.schemas.common import ApiResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    service = AuthService(db)
    try:
        resp = await service.login(req)
        return ApiResponse.ok(data=resp, message="登录成功")
    except ValueError as e:
        return ApiResponse.error(message=f"登录失败: {e}", code=401)


@router.post("/register", response_model=ApiResponse[UserResponse])
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    service = AuthService(db)
    try:
        user = await service.register(req)
        return ApiResponse.ok(data=user, message="注册成功")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.post("/forgot-password", response_model=ApiResponse)
async def forgot_password(
    req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """找回密码"""
    service = AuthService(db)
    try:
        await service.forgot_password(req)
        return ApiResponse.ok(message="密码重置成功，请使用新密码登录")
    except ValueError as e:
        return ApiResponse.error(message=str(e), code=400)


@router.get("/profile", response_model=ApiResponse[ProfileResponse])
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户信息"""
    service = AuthService(db)
    profile = await service.get_profile(user.username)
    return ApiResponse.ok(data=profile)


@router.put("/profile", response_model=ApiResponse[ProfileResponse])
async def update_profile(
    req: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新个人信息"""
    service = AuthService(db)
    profile = await service.update_profile(user.username, req)
    return ApiResponse.ok(data=profile, message="更新成功")
