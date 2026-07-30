"""文件上传与预览路由"""
from __future__ import annotations

import json
import re
import uuid
import zipfile
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Path as RoutePath, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PROJECT_ROOT, settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.models import (
    Assignment,
    AuditLog,
    Course,
    Enrollment,
    PeerReview,
    StoredFile,
    Submission,
    User,
)
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/files", tags=["文件"])

ALLOWED_CONTENT_TYPES = {
    ".pdf": {"application/pdf"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".gif": {"image/gif"},
    ".webp": {"image/webp"},
    ".doc": {"application/msword"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xls": {"application/vnd.ms-excel"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".ppt": {"application/vnd.ms-powerpoint"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
}
ZIP_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".zip"}
OLE_EXTENSIONS = {".doc", ".xls", ".ppt"}
TEXT_EXTENSIONS = {".txt", ".md"}
MAX_ORIGINAL_NAME_LENGTH = 180


def _upload_root() -> Path:
    return settings.upload_path.resolve()


def _safe_original_name(filename: Optional[str]) -> str:
    name = Path(filename or "attachment").name
    name = re.sub(r"[\x00-\x1f\x7f/\\:,]+", "_", name).strip(" ._")
    if not name:
        name = "attachment"
    return name[:MAX_ORIGINAL_NAME_LENGTH]


def _file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def _content_type(content_type: Optional[str]) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _validate_content_signature(ext: str, content: bytes) -> bool:
    sample = content[:512]
    if ext == ".pdf":
        return sample.startswith(b"%PDF-")
    if ext == ".png":
        return sample.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return sample.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return sample.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return sample.startswith(b"RIFF") and sample[8:12] == b"WEBP"
    if ext in ZIP_EXTENSIONS:
        if not sample.startswith(b"PK\x03\x04"):
            return False
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return False
        if ext == ".docx":
            return "word/document.xml" in names
        if ext == ".xlsx":
            return "xl/workbook.xml" in names
        if ext == ".pptx":
            return "ppt/presentation.xml" in names
        return True
    if ext in OLE_EXTENSIONS:
        return sample.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if ext in TEXT_EXTENSIONS:
        try:
            content.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False
    return False


def _validate_upload_file(filename: str, content_type: Optional[str], content: bytes) -> tuple[str, str]:
    ext = _file_extension(filename)
    actual_type = _content_type(content_type)
    if ext not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File extension is not allowed")
    if actual_type not in ALLOWED_CONTENT_TYPES[ext]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File content type is not allowed")
    if not _validate_content_signature(ext, content):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File content does not match extension")
    return ext.lstrip("."), actual_type


async def _read_limited(file: UploadFile) -> bytes:
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large")
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty files are not allowed")
    return b"".join(chunks)


def _resolve_stored_path(stored: StoredFile) -> Path:
    root = _upload_root()
    key = stored.object_key or ""
    candidate = root / key if key and not Path(key).is_absolute() else Path(stored.storage_path)
    if not key:
        candidate = PROJECT_ROOT / stored.storage_path
    resolved = candidate.resolve()
    if root != resolved and root not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return resolved


async def _audit(
    db: AsyncSession,
    request: Request,
    user: User,
    action: str,
    details: dict,
) -> None:
    db.add(
        AuditLog(
            action=action,
            details=json.dumps(details, ensure_ascii=False)[:500],
            ip_address=request.client.host if request.client else None,
            role=user.role,
            timestamp=datetime.now(),
            username=user.username,
        )
    )
    await db.flush()


async def _get_course(db: AsyncSession, course_id: int) -> Course:
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


async def _ensure_course_access(db: AsyncSession, course_id: int, user: User) -> Course:
    course = await _get_course(db, course_id)
    if user.role == "ADMIN":
        return course
    if user.role == "TEACHER" and course.teacher_id == user.id:
        return course
    if user.role == "STUDENT":
        enrolled = await db.execute(
            select(Enrollment.id).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == user.id,
            )
        )
        if enrolled.scalar_one_or_none() is not None:
            return course
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission for this course")


async def _validate_upload_relations(
    db: AsyncSession,
    user: User,
    category: str,
    course_id: Optional[int],
    assignment_id: Optional[int],
    submission_id: Optional[int],
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    assignment = None
    submission = None

    if assignment_id is not None:
        result = await db.execute(select(Assignment).where(Assignment.id == assignment_id))
        assignment = result.scalar_one_or_none()
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
        if course_id is not None and assignment.course_id != course_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assignment does not belong to course")
        course_id = assignment.course_id

    if submission_id is not None:
        result = await db.execute(select(Submission).where(Submission.id == submission_id))
        submission = result.scalar_one_or_none()
        if submission is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
        if assignment_id is not None and submission.assignment_id != assignment_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Submission does not belong to assignment")
        assignment_id = submission.assignment_id
        if assignment is None:
            result = await db.execute(select(Assignment).where(Assignment.id == assignment_id))
            assignment = result.scalar_one_or_none()
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
        if course_id is not None and assignment.course_id != course_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Submission course relation is invalid")
        course_id = assignment.course_id

    if category == "ASSIGNMENT_ATTACHMENT" and user.role not in {"ADMIN", "TEACHER"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only teachers can upload assignment attachments")
    if category == "ASSIGNMENT_ATTACHMENT" and assignment_id is None and course_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Course or assignment is required")
    if category == "SUBMISSION_ATTACHMENT" and assignment_id is not None and user.role == "TEACHER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers cannot upload student submissions")

    if course_id is not None:
        await _ensure_course_access(db, course_id, user)
    if submission is not None and user.role == "STUDENT" and submission.student_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission for this submission")

    return course_id, assignment_id, submission_id


async def _can_student_access_submission(db: AsyncSession, submission_id: int, student_id: int) -> bool:
    result = await db.execute(select(Submission).where(Submission.id == submission_id))
    submission = result.scalar_one_or_none()
    if submission is None:
        return False
    if submission.student_id == student_id:
        return True
    review = await db.execute(
        select(PeerReview.id).where(
            PeerReview.target_submission_id == submission_id,
            PeerReview.reviewer_id == student_id,
        )
    )
    return review.scalar_one_or_none() is not None


async def _ensure_file_access(db: AsyncSession, stored: StoredFile, user: User) -> None:
    if user.role == "ADMIN":
        return

    if stored.submission_id is not None:
        if user.role == "STUDENT" and await _can_student_access_submission(db, stored.submission_id, user.id):
            return
        if user.role == "TEACHER":
            result = await db.execute(
                select(Course.id)
                .join(Assignment, Assignment.course_id == Course.id)
                .join(Submission, Submission.assignment_id == Assignment.id)
                .where(Submission.id == stored.submission_id, Course.teacher_id == user.id)
            )
            if result.scalar_one_or_none() is not None:
                return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission for this file")

    if stored.course_id is not None:
        await _ensure_course_access(db, stored.course_id, user)
        return

    if stored.uploader_user_id == user.id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission for this file")


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    category: str = Query("TEMP_UPLOAD", pattern="^(TEMP_UPLOAD|SUBMISSION_ATTACHMENT|ASSIGNMENT_ATTACHMENT)$"),
    course_id: Optional[int] = Query(None),
    assignment_id: Optional[int] = Query(None),
    submission_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    safe_name = _safe_original_name(file.filename)
    content = await _read_limited(file)
    ext, content_type = _validate_upload_file(safe_name, file.content_type, content)
    course_id, assignment_id, submission_id = await _validate_upload_relations(
        db, user, category, course_id, assignment_id, submission_id
    )

    upload_root = _upload_root()
    object_key = f"{datetime.now().strftime('%Y/%m/%d')}/{uuid.uuid4().hex}.{ext}"
    absolute_path = (upload_root / object_key).resolve()
    if upload_root != absolute_path and upload_root not in absolute_path.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid storage path")
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(content)

    relative_base = Path(settings.upload_dir)
    storage_path = (
        str(relative_base / object_key) if not relative_base.is_absolute() else str(absolute_path)
    ).replace("\\", "/")

    stored = StoredFile(
        original_name=safe_name,
        storage_path=storage_path,
        object_key=object_key,
        bucket="local",
        category=category,
        content_type=content_type,
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
    await _audit(db, request, user, "FILE_UPLOAD", {"file_id": stored.id, "category": category, "size": stored.size})

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


async def _send_file(
    file_id: int,
    request: Request,
    user: User,
    db: AsyncSession,
    action: str,
) -> FileResponse:
    result = await db.execute(select(StoredFile).where(StoredFile.id == file_id))
    stored = result.scalar_one_or_none()
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    await _ensure_file_access(db, stored, user)
    abs_path = _resolve_stored_path(stored)
    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    await _audit(db, request, user, action, {"file_id": stored.id})
    return FileResponse(
        path=str(abs_path),
        filename=stored.original_name,
        media_type=stored.content_type or "application/octet-stream",
    )


@router.get("/{file_id}/preview")
async def preview_file(
    request: Request,
    file_id: int = RoutePath(..., ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _send_file(file_id, request, user, db, "FILE_PREVIEW")


@router.get("/{file_id}/download")
async def download_file(
    request: Request,
    file_id: int = RoutePath(..., ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _send_file(file_id, request, user, db, "FILE_DOWNLOAD")
