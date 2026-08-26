"""ESS API — Configure / Sync for per-user ``.session_storage/{user}/ess``."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from application.api.routes_auth import require_user_id
from application.ess_jobs import ensure_ess_sync, get_ess_job_status
from application import utils

router = APIRouter(prefix="/api/ess", tags=["ess"])

_MAX_RAW_UPLOAD_BYTES = 80 * 1024 * 1024  # 80 MiB


class EssConfigPut(BaseModel):
    foundation_model_parser_enabled: bool | None = None


@router.get("/status")
def ess_status(request: Request) -> dict:
    user_id = require_user_id(request)
    # Do not call ensure_* here — status is polled every ~2.5s during Sync.
    job = get_ess_job_status(user_id)
    files = utils.list_ess_raw_files(user_id)
    converted = Path(utils.ess_converted_dir(user_id))
    md_files = sorted(converted.glob("*.md")) if converted.is_dir() else []
    status = job.get("status") or "idle"
    if status in ("idle", "unchanged") and files:
        status = "ready" if status == "idle" else status
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "raw_dir": utils.ess_raw_dir(user_id),
        "converted_dir": str(converted),
        "markdown_files": [p.name for p in md_files],
        "markdown_count": len(md_files),
        "files": files,
        "exists": len(files) > 0,
        "status": status,
        "foundation_model_parser_enabled": utils.is_ess_foundation_model_parser_enabled(
            user_id
        ),
        "error": job.get("error"),
        "message": job.get("message"),
        "last_success_at": job.get("last_success_at"),
        "progress": job.get("progress"),
    }


@router.get("/config")
def get_ess_config(request: Request) -> dict:
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "raw_dir": utils.ess_raw_dir(user_id),
        "files": utils.list_ess_raw_files(user_id),
        "foundation_model_parser_enabled": utils.is_ess_foundation_model_parser_enabled(
            user_id
        ),
    }


@router.put("/config")
def put_ess_config(body: EssConfigPut, request: Request) -> dict:
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    if body.foundation_model_parser_enabled is not None:
        utils.set_ess_foundation_model_parser_enabled(
            bool(body.foundation_model_parser_enabled),
            user_id=user_id,
        )
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "raw_dir": utils.ess_raw_dir(user_id),
        "files": utils.list_ess_raw_files(user_id),
        "foundation_model_parser_enabled": utils.is_ess_foundation_model_parser_enabled(
            user_id
        ),
    }


@router.post("/raw")
async def upload_ess_raw_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Copy one uploaded document into the user's ``{ess}/raw`` for Sync."""
    user_id = require_user_id(request)
    name = (file.filename or "").strip() or "upload.bin"
    try:
        data = await file.read()
    finally:
        try:
            await file.close()
        except Exception:
            pass

    if not data:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")
    if len(data) > _MAX_RAW_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"파일이 너무 큽니다: {name} "
                f"(최대 {_MAX_RAW_UPLOAD_BYTES // (1024 * 1024)}MB)."
            ),
        )

    try:
        result = utils.save_ess_raw_upload(name, data, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"문서 저장 실패: {exc}",
        ) from exc

    return {
        "ess_dir": result["ess_dir"],
        "raw_dir": result["raw_dir"],
        "saved": result["saved"],
        "count": result["count"],
        "files": utils.list_ess_raw_files(user_id),
    }


@router.post("/sync")
def sync_ess(request: Request, full: bool = Query(False)) -> dict:
    """Enqueue ESS sync for the user's ess directory."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    job = ensure_ess_sync(user_id, full=full)
    files = utils.list_ess_raw_files(user_id)
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "raw_dir": utils.ess_raw_dir(user_id),
        "files": files,
        "exists": len(files) > 0,
        "foundation_model_parser_enabled": utils.is_ess_foundation_model_parser_enabled(
            user_id
        ),
        **job,
    }
