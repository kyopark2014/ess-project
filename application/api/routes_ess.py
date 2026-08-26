"""ESS API — Configure / Sync for per-user ``.session_storage/{user}/ess``."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from application.api.routes_auth import require_user_id
from application.ess_jobs import ensure_ess_sync, get_ess_job_status
from application import utils

router = APIRouter(prefix="/api/ess", tags=["ess"])

# Multipart fallback only (prefer presigned PUT for large PDFs).
_MAX_MULTIPART_DOC_BYTES = 80 * 1024 * 1024  # 80 MiB


class EssConfigPut(BaseModel):
    foundation_model_parser_enabled: bool | None = None


class EssDocsPresignRequest(BaseModel):
    file_name: str = Field(..., min_length=1)
    size: int | None = Field(default=None, ge=0)
    content_type: str | None = None


class EssDocsCompleteRequest(BaseModel):
    file_name: str = Field(..., min_length=1)
    s3_key: str = Field(..., min_length=1)
    size: int | None = Field(default=None, ge=0)
    original_filename: str | None = None


def _load_doc_list_payload(user_id: str, *, enrich: bool = False) -> dict:
    try:
        utils._ensure_ess_on_path()
        from doc_list import load_doc_list, list_documents

        ess = utils.get_user_ess_dir(user_id)
        data = load_doc_list(ess)
        documents = list_documents(ess)
        if enrich:
            documents = utils.enrich_ess_documents_for_ui(
                documents, user_id=user_id, publish_md=True
            )
        return {
            "doc_list": str(Path(ess) / "doc_list.json"),
            "documents": documents,
            "doc_count": len(data.get("documents") or []),
            "doc_list_updated_at": data.get("updated_at"),
            "sharing_url": utils.sharing_url or None,
        }
    except Exception:
        return {
            "doc_list": utils.ess_doc_list_path(user_id),
            "documents": [],
            "doc_count": 0,
            "doc_list_updated_at": None,
            "sharing_url": utils.sharing_url or None,
        }


def _safe_doc_name(name: str) -> str:
    cleaned = Path(unquote(name or "")).name.strip()
    if not cleaned or cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid document name")
    return cleaned


def _resolve_ess_doc_path(user_id: str, filename: str) -> Path:
    docs = Path(utils.ess_docs_dir(user_id))
    path = (docs / filename).resolve()
    try:
        path.relative_to(docs.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document path") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Document not found: {filename}")
    return path


def _assert_ess_doc_size(size: int | None) -> None:
    if size is None:
        return
    if size <= 0:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")
    if size > utils.MAX_ESS_DOC_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"파일이 너무 큽니다 "
                f"(최대 {utils.MAX_ESS_DOC_BYTES // (1024 * 1024)}MB)."
            ),
        )


@router.get("/status")
def ess_status(request: Request) -> dict:
    user_id = require_user_id(request)
    # Do not call ensure_* here — status is polled every ~2.5s during Sync.
    job = get_ess_job_status(user_id)
    files = utils.list_ess_doc_files(user_id)
    docs = Path(utils.ess_docs_dir(user_id))
    converted = Path(utils.ess_converted_dir(user_id))
    # Extraction outputs live next to sources in docs/ (``{stem}.md``).
    md_files = sorted(docs.glob("*.md")) if docs.is_dir() else []
    status = job.get("status") or "idle"
    if status in ("idle", "unchanged") and files:
        status = "ready" if status == "idle" else status
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "docs_dir": utils.ess_docs_dir(user_id),
        "raw_dir": utils.ess_docs_dir(user_id),  # backward-compatible
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
        **_load_doc_list_payload(user_id),
    }


@router.get("/config")
def get_ess_config(request: Request) -> dict:
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "docs_dir": utils.ess_docs_dir(user_id),
        "raw_dir": utils.ess_docs_dir(user_id),
        "files": utils.list_ess_doc_files(user_id),
        "foundation_model_parser_enabled": utils.is_ess_foundation_model_parser_enabled(
            user_id
        ),
        **_load_doc_list_payload(user_id),
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
        "docs_dir": utils.ess_docs_dir(user_id),
        "raw_dir": utils.ess_docs_dir(user_id),
        "files": utils.list_ess_doc_files(user_id),
        "foundation_model_parser_enabled": utils.is_ess_foundation_model_parser_enabled(
            user_id
        ),
        **_load_doc_list_payload(user_id),
    }


@router.get("/doc-list")
def get_ess_doc_list(
    request: Request,
    publish_md: bool = Query(True),
) -> dict:
    """Return ESS documents with PDF/MD view URLs.

    Markdown files are copied to ``artifacts/{project}/{user}/md/`` and uploaded
    to S3 so CloudFront can serve them. PDFs use ``session-uploads/{user}/ess/``.
    """
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    payload = _load_doc_list_payload(user_id, enrich=False)
    payload["documents"] = utils.enrich_ess_documents_for_ui(
        payload.get("documents") or [],
        user_id=user_id,
        publish_md=bool(publish_md),
    )
    payload["doc_count"] = len(payload["documents"])
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "docs_dir": utils.ess_docs_dir(user_id),
        **payload,
    }


@router.get("/documents/{filename}/pdf")
def get_ess_document_pdf(filename: str, request: Request):
    """Open PDF in-browser: redirect to CloudFront when available, else stream local file."""
    user_id = require_user_id(request)
    name = _safe_doc_name(filename)
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Not a PDF document")

    if utils.head_ess_pdf_on_s3(name, user_id=user_id):
        cf = utils.ess_pdf_public_url(name, user_id=user_id)
        if cf:
            return RedirectResponse(url=cf, status_code=302)

    path = _resolve_ess_doc_path(user_id, name)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=name,
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


@router.get("/documents/{filename}/markdown")
def get_ess_document_markdown_viewer(filename: str, request: Request):
    """Markdown viewer HTML for a new browser tab."""
    user_id = require_user_id(request)
    name = _safe_doc_name(filename)
    stem = Path(name).stem
    # Accept either ``foo.md`` or the source pdf name ``foo.pdf``.
    md_name = name if name.lower().endswith(".md") else f"{stem}.md"
    docs = Path(utils.ess_docs_dir(user_id))
    md_path = docs / md_name
    if not md_path.is_file():
        # Fall back to artifacts/md copy.
        alt = Path(utils.ess_md_local_artifacts_path(md_name, user_id=user_id))
        if alt.is_file():
            md_path = alt
        else:
            raise HTTPException(status_code=404, detail=f"Markdown not found: {md_name}")

    # Ensure CloudFront copy exists (best-effort).
    published = utils.publish_ess_markdown_to_artifacts(
        md_path, user_id=user_id, file_name=md_name
    )
    raw_url = (published or {}).get("url") or ""

    try:
        text = md_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = md_path.read_text(encoding="utf-8", errors="replace")

    title = html.escape(md_name)
    # JSON-encode for safe embedding inside <script>.
    payload = json.dumps(text, ensure_ascii=False)
    raw_link = (
        f'<a class="raw" href="{html.escape(raw_url)}" target="_blank" rel="noopener">Raw (CloudFront)</a>'
        if raw_url
        else ""
    )
    page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/github-markdown-css@5.8.1/github-markdown.min.css" />
  <style>
    :root {{ color-scheme: light dark; }}
    body {{
      margin: 0;
      background: #0d1117;
      color: #e6edf3;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    }}
    .topbar {{
      position: sticky; top: 0; z-index: 2;
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 10px 20px;
      border-bottom: 1px solid #30363d;
      background: rgba(13, 17, 23, 0.92);
      backdrop-filter: blur(8px);
    }}
    .topbar h1 {{
      margin: 0; font-size: 14px; font-weight: 600;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}
    .topbar a.raw {{
      color: #58a6ff; text-decoration: none; font-size: 13px; white-space: nowrap;
    }}
    .wrap {{
      box-sizing: border-box;
      max-width: 980px;
      margin: 0 auto;
      padding: 24px 20px 64px;
    }}
    .markdown-body {{
      background: transparent;
      color: #e6edf3;
    }}
    @media (prefers-color-scheme: light) {{
      body {{ background: #ffffff; color: #1f2328; }}
      .topbar {{ background: rgba(255,255,255,0.92); border-bottom-color: #d0d7de; }}
      .markdown-body {{ color: #1f2328; }}
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <h1>{title}</h1>
    {raw_link}
  </div>
  <div class="wrap">
    <article id="content" class="markdown-body">Loading…</article>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js"></script>
  <script>
    const source = {payload};
    const el = document.getElementById("content");
    try {{
      marked.setOptions({{ gfm: true, breaks: false }});
      el.innerHTML = marked.parse(source);
    }} catch (err) {{
      el.textContent = "Failed to render markdown: " + err;
    }}
  </script>
</body>
</html>
"""
    return HTMLResponse(content=page, media_type="text/html; charset=utf-8")


@router.post("/docs/presign")
def ess_docs_presign(body: EssDocsPresignRequest, request: Request) -> dict:
    """Return a short-lived S3 PUT URL (browser → S3, bypasses API body limits)."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    _assert_ess_doc_size(body.size)

    try:
        presign = utils.generate_ess_docs_presigned_put(
            body.file_name, user_id=user_id
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"업로드 URL 생성 실패: {exc}"
        ) from exc
    if not presign or not presign.get("upload_url"):
        raise HTTPException(status_code=500, detail="업로드 URL 생성 실패")

    return {
        "ok": True,
        "file_name": presign["file_name"],
        "original_filename": presign.get("original_filename") or body.file_name,
        "sanitized": bool(presign.get("sanitized")),
        "s3_key": presign["s3_key"],
        "content_type": presign.get("content_type"),
        "upload_url": presign["upload_url"],
        "headers": presign.get("headers") or {},
        "expires_in": presign.get("expires_in"),
        "docs_dir": utils.ess_docs_dir(user_id),
    }


@router.post("/docs/complete")
def ess_docs_complete(body: EssDocsCompleteRequest, request: Request) -> dict:
    """Confirm a presigned PUT and materialize the object into ``ess/docs/``."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    _assert_ess_doc_size(body.size)

    try:
        utils._ensure_ess_on_path()
        from doc_list import sanitize_ess_filename

        safe_name = sanitize_ess_filename(body.file_name)
    except Exception:
        safe_name = Path(body.file_name).name

    expected_key = utils.ess_docs_s3_key(safe_name, user_id=user_id)
    key = (body.s3_key or "").strip()
    if key != expected_key:
        raise HTTPException(status_code=400, detail="Invalid upload target")

    head = utils.head_session_upload_object(key)
    if not head:
        raise HTTPException(status_code=404, detail="Uploaded object not found")
    content_length = int(head.get("content_length") or 0)
    if content_length <= 0:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")
    if body.size is not None and content_length != body.size:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Uploaded size mismatch (expected {body.size}, got {content_length})"
            ),
        )
    _assert_ess_doc_size(content_length)

    result = utils.materialize_ess_docs_from_s3(
        key,
        safe_name,
        user_id=user_id,
        original_filename=body.original_filename or body.file_name,
    )
    if not result:
        raise HTTPException(
            status_code=500, detail="Failed to save file to ess/docs"
        )

    return {
        "ok": True,
        "ess_dir": result["ess_dir"],
        "docs_dir": result.get("docs_dir"),
        "raw_dir": result.get("docs_dir"),
        "saved": result["saved"],
        "count": result.get("count", 1),
        "s3_key": key,
        "files": utils.list_ess_doc_files(user_id),
        **_load_doc_list_payload(user_id),
    }


async def _upload_ess_doc_multipart(request: Request, file: UploadFile) -> dict:
    """Legacy multipart upload (small files only). Prefer presign flow."""
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
    if len(data) > _MAX_MULTIPART_DOC_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"파일이 너무 큽니다: {name} "
                f"(최대 {_MAX_MULTIPART_DOC_BYTES // (1024 * 1024)}MB). "
                "브라우저를 강력 새로고침(Cmd+Shift+R / Ctrl+Shift+R)한 뒤 "
                "다시 업로드하세요. (presigned S3 업로드로 전환됩니다)"
            ),
        )

    try:
        result = utils.save_ess_doc_upload(name, data, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"문서 저장 실패: {exc}",
        ) from exc

    return {
        "ess_dir": result["ess_dir"],
        "docs_dir": result.get("docs_dir") or result.get("raw_dir"),
        "raw_dir": result.get("docs_dir") or result.get("raw_dir"),
        "saved": result["saved"],
        "count": result["count"],
        "files": utils.list_ess_doc_files(user_id),
        **_load_doc_list_payload(user_id),
    }


@router.post("/docs")
async def upload_ess_doc_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Legacy multipart path — the UI uses ``/docs/presign`` + ``/docs/complete``."""
    return await _upload_ess_doc_multipart(request, file)


@router.post("/raw")
async def upload_ess_raw_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Deprecated alias for ``POST /api/ess/docs``."""
    return await _upload_ess_doc_multipart(request, file)


@router.post("/sync")
def sync_ess(
    request: Request,
    full: bool = Query(False),
    model: str | None = Query(None),
) -> dict:
    """Enqueue ESS sync for the user's ess directory.

    ``model`` is the UI-selected display name (e.g. ``Claude 4.6 Sonnet``)
    used by Foundation Model Parser vision extraction.
    """
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    job = ensure_ess_sync(user_id, full=full, model=model)
    files = utils.list_ess_doc_files(user_id)
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "docs_dir": utils.ess_docs_dir(user_id),
        "raw_dir": utils.ess_docs_dir(user_id),
        "files": files,
        "exists": len(files) > 0,
        "foundation_model_parser_enabled": utils.is_ess_foundation_model_parser_enabled(
            user_id
        ),
        **_load_doc_list_payload(user_id),
        **job,
    }
