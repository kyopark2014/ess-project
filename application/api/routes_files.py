import logging

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from application.api.routes_auth import require_user_id
from application.services.file_upload_service import (
    FileUploadServiceError,
    complete_load_file_upload,
    create_load_file_presign,
    sanitize_image_filename,
    sanitize_load_filename,
    upload_chat_image,
    upload_load_file,
)

logger = logging.getLogger("routes_files")

router = APIRouter(prefix="/api/files", tags=["files"])


class LoadFilePresignRequest(BaseModel):
    file_name: str = Field(..., min_length=1)
    size: int | None = Field(default=None, ge=0)
    content_type: str | None = None


class LoadFileCompleteRequest(BaseModel):
    file_name: str = Field(..., min_length=1)
    s3_key: str = Field(..., min_length=1)
    size: int | None = Field(default=None, ge=0)


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """Upload an image to S3 (images/{user_id}/) for chat attachment. No Knowledge Base sync."""
    user_id = require_user_id(request)

    try:
        file_name = sanitize_image_filename(file.filename or "pasted.png")
        file_bytes = await file.read()
        return upload_chat_image(file_bytes, file_name, user_id=user_id)
    except FileUploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/load/presign")
async def load_file_presign(request: Request, body: LoadFilePresignRequest):
    """Return a short-lived S3 PUT URL so the browser can upload past ECS body limits."""
    user_id = require_user_id(request)

    try:
        return create_load_file_presign(
            body.file_name,
            user_id=user_id,
            size=body.size,
        )
    except FileUploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/load/complete")
async def load_file_complete(request: Request, body: LoadFileCompleteRequest):
    """Confirm a presigned PUT, mirror into SESSION_STORAGE, return workspace path."""
    user_id = require_user_id(request)

    try:
        return complete_load_file_upload(
            body.file_name,
            body.s3_key,
            user_id=user_id,
            size=body.size,
        )
    except FileUploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/load")
async def load_file(request: Request, file: UploadFile = File(...)):
    """Upload a Load-files attachment under SESSION_STORAGE_DIR/{user}/upload/.

    Returns ``workspace_path`` (absolute local path) for the agent payload —
    not a CloudFront URL.

    Prefer ``/load/presign`` + browser PUT for large files (>~80MB) so the body
    does not traverse ECS/ALB.
    """
    user_id = require_user_id(request)

    try:
        file_name = sanitize_load_filename(file.filename or "upload.bin")
        file_bytes = await file.read()
        return upload_load_file(file_bytes, file_name, user_id=user_id)
    except FileUploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
