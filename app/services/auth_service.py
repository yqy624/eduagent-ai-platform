"""认证服务"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware.auth import (
    create_access_token,
    hash_password,
    verify_password,
)
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


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def login(self, req: LoginRequest) -> LoginResponse:
        result = await self.db.execute(
            select(User).where(User.username == req.username)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        if not verify_password(req.password, user.password):
            raise ValueError("密码错误")
        if user.role != req.role:
            raise ValueError(f"所选角色与账号不匹配，当前角色为 {user.role}")

        user.last_login = datetime.now()
        await self.db.flush()

        token = create_access_token(user.username, user.role)
        redirect_map = {
            "ADMIN": "/static/admin/dashboard.html",
            "TEACHER": "/static/teacher/dashboard.html",
            "STUDENT": "/static/student/dashboard.html",
        }
        return LoginResponse(
            token=token,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            redirect_url=redirect_map.get(user.role, "/"),
            expires_in=86400000,
        )

    async def register(self, req: RegisterRequest) -> UserResponse:
        result = await self.db.execute(
            select(User).where(User.username == req.username)
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError("用户名已存在")

        if req.role not in ("ADMIN", "TEACHER", "STUDENT"):
            raise ValueError("无效角色，可用: ADMIN, TEACHER, STUDENT")

        user = User(
            username=req.username,
            password=hash_password(req.password),
            display_name=req.display_name or req.username,
            email=req.email,
            role=req.role,
            enabled=True,
            created_at=datetime.now(),
        )
        self.db.add(user)
        await self.db.flush()
        return self._user_to_response(user)

    async def forgot_password(self, req: ForgotPasswordRequest):
        result = await self.db.execute(
            select(User).where(User.username == req.username)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        if user.role != req.role:
            raise ValueError("账号角色不匹配")
        if req.email and user.email and user.email.lower() != req.email.lower():
            raise ValueError("邮箱不匹配")
        user.password = hash_password(req.new_password)
        await self.db.flush()

    async def get_profile(self, username: str) -> ProfileResponse:
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        return ProfileResponse(
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            role=user.role,
        )

    async def update_profile(
        self, username: str, req: ProfileUpdateRequest
    ) -> ProfileResponse:
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        if req.display_name:
            user.display_name = req.display_name
        if req.email is not None:
            user.email = req.email
        if req.new_password:
            user.password = hash_password(req.new_password)
        await self.db.flush()
        return ProfileResponse(
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            role=user.role,
        )

    def _user_to_response(self, user: User) -> UserResponse:
        return UserResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            role=user.role,
            enabled=user.enabled,
            last_login=user.last_login.isoformat() if user.last_login else None,
            created_at=user.created_at.isoformat() if user.created_at else None,
        )
