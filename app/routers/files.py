"""文件上传与预览路由"""
import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.models import StoredFile, User
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/files", tags=["文件"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    category: str = Query("TEMP_UPLOAD", pattern="^(TEMP_UPLOAD|SUBMISSION_ATTACHMENT|ASSIGNMENT_ATTACHMENT)$"),
    course_id: Optional[int] = Query(None),
    assignment_id: Optional[int] = Query(None),
    submission_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传文件"""
    ext = ""
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1]

    object_key = f"{datetime.now().strftime('%Y/%m/%d')}/{uuid.uuid4().hex}.{ext}"
    relative_path = f"uploads/{object_key}"
    absolute_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), relative_path
    )
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)

    content = await file.read()
    with open(absolute_path, "wb") as f:
        f.write(content)

    stored = StoredFile(
        original_name=file.filename or "unnamed",
        storage_path=relative_path.replace("\\", "/"),
        object_key=object_key,
        bucket="local",
        category=category,
        content_type=file.content_type,
        extension=ext,
        size=len(content),
        course_id=course_id,
        assignment_id=assignment_id,
        submission_id=submission_id,
        uploader_user_id=user.id,
        created_at=datetime.now(),
    )
    db.add(stored)
    await db.flush()

    return ApiResponse.ok(
        data={
            "id": stored.id,
            "original_name": stored.original_name,
            "storage_path": stored.storage_path,
            "size": stored.size,
            "content_type": stored.content_type,
        },
        message="上传成功",
    )


@router.get("/{file_id}/preview")
async def preview_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    """预览/下载文件"""
    from sqlalchemy import select
    result = await db.execute(select(StoredFile).where(StoredFile.id == file_id))
    stored = result.scalar_one_or_none()
    if stored is None:
        raise HTTPException(status_code=404, detail="文件不存在")

    abs_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        stored.storage_path.replace("\\", "/"),
    )
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="文件已被删除")

    return FileResponse(
        path=abs_path,
        filename=stored.original_name,
        media_type=stored.content_type or "application/octet-stream",
    )


@router.get("/{file_id}/download")
async def download_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    """下载文件（与预览相同）"""
    return await preview_file(file_id, db)
