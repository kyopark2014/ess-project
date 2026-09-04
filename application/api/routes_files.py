import logging

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from application.api.routes_auth import require_user_id
from application.viewer_html import build_text_viewer_page
from application.services.file_upload_service import (
    INLINE_BINARY_EXTENSIONS,
    TEXT_VIEWER_EXTENSIONS,
    TEXT_VIEWER_MAX_BYTES,
    FileUploadServiceError,
    complete_load_file_upload,
    create_load_file_presign,
    read_session_upload_bytes,
    sanitize_image_filename,
    sanitize_load_filename,
    stream_session_upload,
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


@router.get("/view/{filename}")
def view_loaded_file(
    filename: str,
    request: Request,
    download: int = Query(0),
):
    """Open a Load-files attachment in a new browser tab (viewer or inline).

    Reads from ``agentcore-sessions/{user}/upload/{filename}``. PDF/images stream
    inline; text/markdown/json render in an HTML viewer; other types download.

    Viewer HTML is CSP-safe (no inline scripts / CDN) so it works under the app
    Content-Security-Policy.
    """
    user_id = require_user_id(request)
    try:
        safe_name = sanitize_load_filename(filename)
    except FileUploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    ext = Path(safe_name).suffix.lower()
    force_download = bool(download)

    try:
        if force_download or (
            ext not in TEXT_VIEWER_EXTENSIONS and ext not in INLINE_BINARY_EXTENSIONS
        ):
            return stream_session_upload(
                safe_name, user_id=user_id, as_attachment=True
            )

        if ext in INLINE_BINARY_EXTENSIONS:
            return stream_session_upload(
                safe_name, user_id=user_id, as_attachment=False
            )

        data, _content_type = read_session_upload_bytes(
            safe_name,
            user_id=user_id,
            max_bytes=TEXT_VIEWER_MAX_BYTES,
        )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")

        as_markdown = ext in {".md", ".markdown"}
        page = build_text_viewer_page(
            safe_name,
            text,
            as_markdown=as_markdown,
            download_href=f"/api/files/view/{quote(safe_name)}?download=1",
        )
        return HTMLResponse(content=page, media_type="text/html; charset=utf-8")
    except FileUploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

