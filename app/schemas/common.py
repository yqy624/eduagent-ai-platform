"""通用 Pydantic Schema"""
from datetime import datetime
from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""
    code: int = 200
    message: str = "success"
    data: Optional[T] = None

    @staticmethod
    def ok(data: Any = None, message: str = "success"):
        return ApiResponse(code=200, message=message, data=data)

    @staticmethod
    def error(message: str = "error", code: int = 400):
        return ApiResponse(code=code, message=message, data=None)


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int
