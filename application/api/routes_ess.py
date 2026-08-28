"""ESS API — Configure / Sync for per-user ``.session_storage/{user}/ess``."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
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
            "doc_list": str(Path(ess) / "regulations_list.json"),
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


def _load_project_list_payload(user_id: str, *, enrich: bool = False) -> dict:
    try:
        utils._ensure_ess_on_path()
        from doc_list import PROJECTS, load_doc_list, list_documents

        ess = utils.get_user_ess_dir(user_id)
        data = load_doc_list(ess, PROJECTS)
        documents = list_documents(ess, PROJECTS)
        if enrich:
            documents = utils.enrich_ess_documents_for_ui(
                documents, user_id=user_id, publish_md=True, kind="project"
            )
        return {
            "project_list": str(Path(ess) / "project_list.json"),
            "doc_list": str(Path(ess) / "project_list.json"),
            "documents": documents,
            "doc_count": len(data.get("documents") or []),
            "doc_list_updated_at": data.get("updated_at"),
            "sharing_url": utils.sharing_url or None,
        }
    except Exception:
        return {
            "project_list": utils.ess_project_list_path(user_id),
            "doc_list": utils.ess_project_list_path(user_id),
            "documents": [],
            "doc_count": 0,
            "doc_list_updated_at": None,
            "sharing_url": utils.sharing_url or None,
        }


def _load_drawings_list_payload(user_id: str, *, enrich: bool = False) -> dict:
    try:
        utils._ensure_ess_on_path()
        from doc_list import DRAWINGS, load_doc_list, list_documents

        ess = utils.get_user_ess_dir(user_id)
        data = load_doc_list(ess, DRAWINGS)
        documents = list_documents(ess, DRAWINGS)
        if enrich:
            documents = utils.enrich_ess_documents_for_ui(
                documents, user_id=user_id, publish_md=True, kind="drawing"
            )
        return {
            "drawings_list": str(Path(ess) / "drawings_list.json"),
            "doc_list": str(Path(ess) / "drawings_list.json"),
            "documents": documents,
            "doc_count": len(data.get("documents") or []),
            "doc_list_updated_at": data.get("updated_at"),
            "sharing_url": utils.sharing_url or None,
        }
    except Exception:
        return {
            "drawings_list": utils.ess_drawings_list_path(user_id),
            "doc_list": utils.ess_drawings_list_path(user_id),
            "documents": [],
            "doc_count": 0,
            "doc_list_updated_at": None,
            "sharing_url": utils.sharing_url or None,
        }


def _load_test_case_list_payload(user_id: str, *, enrich: bool = False) -> dict:
    try:
        utils._ensure_ess_on_path()
        from doc_list import TEST_CASES, load_doc_list, list_documents

        ess = utils.get_user_ess_dir(user_id)
        data = load_doc_list(ess, TEST_CASES)
        documents = list_documents(ess, TEST_CASES)
        if enrich:
            documents = utils.enrich_ess_test_cases_for_ui(
                documents, user_id=user_id
            )
        return {
            "test_cases_list": str(Path(ess) / "test_cases_list.json"),
            "doc_list": str(Path(ess) / "test_cases_list.json"),
            "documents": documents,
            "doc_count": len(data.get("documents") or []),
            "doc_list_updated_at": data.get("updated_at"),
            "sharing_url": utils.sharing_url or None,
        }
    except Exception:
        return {
            "test_cases_list": utils.ess_test_cases_list_path(user_id),
            "doc_list": utils.ess_test_cases_list_path(user_id),
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


def _resolve_ess_doc_path(
    user_id: str,
    filename: str,
    *,
    kind: str = "regulation",
) -> Path:
    if kind == "test_case":
        bases = [utils.ess_test_cases_dir(user_id)]
    elif kind == "project":
        bases = [utils.ess_projects_dir(user_id), utils.ess_docs_dir(user_id)]
    elif kind == "drawing":
        bases = [
            utils.ess_drawings_dir(user_id),
            utils.ess_docs_dir(user_id),
            utils.ess_projects_dir(user_id),
        ]
    else:
        bases = [
            utils.ess_docs_dir(user_id),
            utils.ess_projects_dir(user_id),
            utils.ess_drawings_dir(user_id),
        ]

    for base_str in bases:
        docs = Path(base_str)
        path = (docs / filename).resolve()
        try:
            path.relative_to(docs.resolve())
        except ValueError:
            continue
        if path.is_file():
            return path
    raise HTTPException(status_code=404, detail=f"Document not found: {filename}")


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


def _ess_folder_scope(kind: str) -> str:
    normalized = (kind or "regulation").strip().lower()
    if normalized == "project":
        return "project"
    if normalized == "drawing":
        return "drawing"
    return "regulation"


def _ess_folder_dir(user_id: str, scope: str) -> str:
    if scope == "project":
        return utils.ess_projects_dir(user_id)
    if scope == "drawing":
        return utils.ess_drawings_dir(user_id)
    return utils.ess_docs_dir(user_id)


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
    """Return ESS regulation documents with PDF/MD view URLs.

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
        kind="regulation",
    )
    payload["doc_count"] = len(payload["documents"])
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "docs_dir": utils.ess_docs_dir(user_id),
        **payload,
    }


@router.get("/project-list")
def get_ess_project_list(
    request: Request,
    publish_md: bool = Query(True),
) -> dict:
    """Return ESS project documents with PDF/MD view URLs (``project_list.json``)."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    payload = _load_project_list_payload(user_id, enrich=False)
    payload["documents"] = utils.enrich_ess_documents_for_ui(
        payload.get("documents") or [],
        user_id=user_id,
        publish_md=bool(publish_md),
        kind="project",
    )
    payload["doc_count"] = len(payload["documents"])
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "projects_dir": utils.ess_projects_dir(user_id),
        "docs_dir": utils.ess_projects_dir(user_id),
        **payload,
    }


@router.get("/drawing-list")
def get_ess_drawing_list(
    request: Request,
    publish_md: bool = Query(True),
) -> dict:
    """Return ESS drawing documents with PDF/MD view URLs (``drawings_list.json``)."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    payload = _load_drawings_list_payload(user_id, enrich=False)
    payload["documents"] = utils.enrich_ess_documents_for_ui(
        payload.get("documents") or [],
        user_id=user_id,
        publish_md=bool(publish_md),
        kind="drawing",
    )
    payload["doc_count"] = len(payload["documents"])
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "drawings_dir": utils.ess_drawings_dir(user_id),
        "docs_dir": utils.ess_drawings_dir(user_id),
        **payload,
    }


@router.get("/test-case-list")
def get_ess_test_case_list(request: Request) -> dict:
    """Return ESS test-case documents with xlsx/json view URLs (``test_cases_list.json``)."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    payload = _load_test_case_list_payload(user_id, enrich=False)
    payload["documents"] = utils.enrich_ess_test_cases_for_ui(
        payload.get("documents") or [],
        user_id=user_id,
    )
    payload["doc_count"] = len(payload["documents"])
    return {
        "ess_dir": utils.get_user_ess_dir(user_id),
        "test_cases_dir": utils.ess_test_cases_dir(user_id),
        "docs_dir": utils.ess_test_cases_dir(user_id),
        **payload,
    }


@router.delete("/documents/{filename}")
def api_delete_ess_document(
    filename: str,
    request: Request,
    kind: str = Query("regulation"),
) -> dict:
    """Delete an ESS document (source + JSON/MD sidecars + list entry).

    ``kind``: ``regulation`` | ``project`` | ``drawing`` | ``test_case``
    """
    user_id = require_user_id(request)
    name = _safe_doc_name(filename)
    scope = (kind or "regulation").strip().lower()
    if scope not in {"regulation", "project", "drawing", "test_case"}:
        raise HTTPException(
            status_code=400,
            detail="kind must be regulation, project, drawing, or test_case",
        )
    try:
        return utils.delete_ess_document(user_id, name, kind=scope)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/documents/{filename}/pdf")
def get_ess_document_pdf(
    filename: str,
    request: Request,
    kind: str = Query("regulation"),
):
    """Open PDF in-browser: stream local file, else S3; do not redirect to CloudFront.

    ``/session-uploads/*`` must be an S3 cache behavior on CloudFront for direct
    ``pdf_url`` links to work in a new tab. The API route stays reliable by
    serving bytes from ECS/S3 instead of a 302 to CloudFront.
    """
    user_id = require_user_id(request)
    name = _safe_doc_name(filename)
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Not a PDF document")

    scope = _ess_folder_scope(kind)
    try:
        path = _resolve_ess_doc_path(user_id, name, kind=scope)
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=name,
            headers={"Content-Disposition": f'inline; filename="{name}"'},
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise

    streamed = utils.stream_ess_pdf_from_s3(name, user_id=user_id, kind=scope)
    if streamed is not None:
        return streamed

    raise HTTPException(status_code=404, detail=f"Document not found: {name}")


@router.get("/documents/{filename}/markdown")
def get_ess_document_markdown_viewer(
    filename: str,
    request: Request,
    kind: str = Query("regulation"),
):
    """Markdown viewer HTML for a new browser tab."""
    user_id = require_user_id(request)
    name = _safe_doc_name(filename)
    stem = Path(name).stem
    # Accept either ``foo.md`` or the source pdf name ``foo.pdf``.
    md_name = name if name.lower().endswith(".md") else f"{stem}.md"
    scope = _ess_folder_scope(kind)
    docs = Path(_ess_folder_dir(user_id, scope))
    md_path = docs / md_name
    if not md_path.is_file():
        # Try other ESS folders, then artifacts/md copy.
        alt_dirs = [
            _ess_folder_dir(user_id, folder)
            for folder in ("regulation", "project", "drawing")
            if folder != scope
        ]
        for alt_str in alt_dirs:
            alt_docs = Path(alt_str)
            if (alt_docs / md_name).is_file():
                md_path = alt_docs / md_name
                break
        else:
            alt = Path(utils.ess_md_local_artifacts_path(md_name, user_id=user_id))
            if alt.is_file():
                md_path = alt
            else:
                raise HTTPException(
                    status_code=404, detail=f"Markdown not found: {md_name}"
                )

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


@router.get("/artifacts/tc/{filename}")
def get_ess_testcase_draft_xlsx(filename: str, request: Request):
    """Download a draft test-case workbook from ``{user}/artifacts/tc/``."""
    user_id = require_user_id(request)
    xlsx_name = _safe_doc_name(filename)
    if not xlsx_name.lower().endswith(".xlsx"):
        xlsx_name = f"{Path(xlsx_name).stem}.xlsx"
    local_path = Path(utils.ess_tc_local_artifacts_path(xlsx_name, user_id=user_id))
    if not local_path.is_file():
        raise HTTPException(status_code=404, detail="Draft test-case file not found")
    return FileResponse(
        local_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=xlsx_name,
        headers={"Content-Disposition": f'attachment; filename="{xlsx_name}"'},
    )


@router.get("/documents/{filename}/xlsx")
def get_ess_document_xlsx(filename: str, request: Request):
    """Download / open a test-case Excel workbook."""
    user_id = require_user_id(request)
    name = _safe_doc_name(filename)
    stem = Path(name).stem
    xlsx_name = name if name.lower().endswith(".xlsx") else f"{stem}.xlsx"
    path = _resolve_ess_doc_path(user_id, xlsx_name, kind="test_case")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=xlsx_name,
        headers={"Content-Disposition": f'attachment; filename="{xlsx_name}"'},
    )


@router.get("/documents/{filename}/json")
def get_ess_document_json_viewer(filename: str, request: Request):
    """HTML table viewer for a test-case JSON sidecar (new browser tab)."""
    user_id = require_user_id(request)
    name = _safe_doc_name(filename)
    stem = Path(name).stem
    json_name = name if name.lower().endswith(".json") else f"{stem}.json"
    path = _resolve_ess_doc_path(user_id, json_name, kind="test_case")

    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
    except json.JSONDecodeError:
        data = None

    title_raw = json_name
    standard = ""
    cases: list = []
    if isinstance(data, dict):
        title_raw = str(data.get("title") or title_raw)
        standard = str(data.get("standard") or "")
        raw_cases = data.get("cases")
        if isinstance(raw_cases, list):
            cases = [c for c in raw_cases if isinstance(c, dict)]
    elif isinstance(data, list):
        cases = [c for c in data if isinstance(c, dict)]

    title = html.escape(title_raw)
    std_html = html.escape(standard) if standard else ""
    payload = json.dumps(cases, ensure_ascii=False)
    meta = (
        f'<span class="meta">{std_html} · {len(cases)} cases</span>'
        if standard
        else f'<span class="meta">{len(cases)} cases</span>'
    )
    page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
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
    .topbar .meta {{ color: #8b949e; font-size: 13px; white-space: nowrap; }}
    .wrap {{
      box-sizing: border-box;
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px 16px 64px;
      overflow-x: auto;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 13px;
    }}
    th, td {{
      border: 1px solid #30363d;
      padding: 8px 10px;
      vertical-align: top;
      text-align: left;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    th {{
      background: #161b22;
      position: sticky; top: 42px;
      z-index: 1;
    }}
    tr:nth-child(even) td {{ background: #11161d; }}
    .empty {{ color: #8b949e; padding: 24px 0; }}
    @media (prefers-color-scheme: light) {{
      body {{ background: #ffffff; color: #1f2328; }}
      .topbar {{ background: rgba(255,255,255,0.92); border-bottom-color: #d0d7de; }}
      .topbar .meta {{ color: #656d76; }}
      th, td {{ border-color: #d0d7de; }}
      th {{ background: #f6f8fa; }}
      tr:nth-child(even) td {{ background: #f6f8fa; }}
      .empty {{ color: #656d76; }}
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <h1>{title}</h1>
    {meta}
  </div>
  <div class="wrap">
    <div id="content" class="empty">Loading…</div>
  </div>
  <script>
    const cases = {payload};
    const el = document.getElementById("content");
    if (!Array.isArray(cases) || cases.length === 0) {{
      el.textContent = "표시할 테스트케이스가 없습니다.";
    }} else {{
      const preferred = ["규격명", "항목", "원문", "기준", "판정결과", "비고"];
      const keySet = new Set();
      for (const row of cases) {{
        Object.keys(row || {{}}).forEach((k) => keySet.add(k));
      }}
      const keys = [
        ...preferred.filter((k) => keySet.has(k)),
        ...[...keySet].filter((k) => !preferred.includes(k)),
      ];
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const hr = document.createElement("tr");
      for (const k of keys) {{
        const th = document.createElement("th");
        th.textContent = k;
        hr.appendChild(th);
      }}
      thead.appendChild(hr);
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const row of cases) {{
        const tr = document.createElement("tr");
        for (const k of keys) {{
          const td = document.createElement("td");
          const v = row[k];
          td.textContent = v == null ? "" : String(v);
          tr.appendChild(td);
        }}
        tbody.appendChild(tr);
      }}
      table.appendChild(tbody);
      el.className = "";
      el.replaceChildren(table);
    }}
  </script>
</body>
</html>
"""
    return HTMLResponse(content=page, media_type="text/html; charset=utf-8")


@router.post("/regulations/presign")
def ess_regulations_presign(body: EssDocsPresignRequest, request: Request) -> dict:
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


@router.post("/regulations/complete")
def ess_regulations_complete(body: EssDocsCompleteRequest, request: Request) -> dict:
    """Confirm a presigned PUT and materialize the object into ``ess/regulations/``."""
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
            status_code=500, detail="Failed to save file to ess/regulations"
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


@router.post("/regulations")
async def upload_ess_regulation_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Legacy multipart path — the UI uses ``/regulations/presign`` + ``/regulations/complete``."""
    return await _upload_ess_doc_multipart(request, file)


@router.post("/projects/presign")
def ess_projects_presign(body: EssDocsPresignRequest, request: Request) -> dict:
    """Return a short-lived S3 PUT URL for project document uploads."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    _assert_ess_doc_size(body.size)

    try:
        presign = utils.generate_ess_projects_presigned_put(
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
        "projects_dir": utils.ess_projects_dir(user_id),
        "docs_dir": utils.ess_projects_dir(user_id),
    }


@router.post("/projects/complete")
def ess_projects_complete(body: EssDocsCompleteRequest, request: Request) -> dict:
    """Confirm a presigned PUT and materialize the object into ``ess/projects/``."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    _assert_ess_doc_size(body.size)

    try:
        utils._ensure_ess_on_path()
        from doc_list import sanitize_ess_filename

        safe_name = sanitize_ess_filename(body.file_name)
    except Exception:
        safe_name = Path(body.file_name).name

    expected_key = utils.ess_projects_s3_key(safe_name, user_id=user_id)
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

    result = utils.materialize_ess_projects_from_s3(
        key,
        safe_name,
        user_id=user_id,
        original_filename=body.original_filename or body.file_name,
    )
    if not result:
        raise HTTPException(
            status_code=500, detail="Failed to save file to ess/projects"
        )

    return {
        "ok": True,
        "ess_dir": result["ess_dir"],
        "projects_dir": result.get("projects_dir"),
        "docs_dir": result.get("projects_dir"),
        "raw_dir": result.get("projects_dir"),
        "saved": result["saved"],
        "count": result.get("count", 1),
        "s3_key": key,
        "files": utils.list_ess_project_files(user_id),
        **_load_project_list_payload(user_id),
    }


async def _upload_ess_project_multipart(request: Request, file: UploadFile) -> dict:
    """Legacy multipart upload for project docs (small files only)."""
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
        result = utils.save_ess_project_upload(name, data, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"문서 저장 실패: {exc}",
        ) from exc

    return {
        "ess_dir": result["ess_dir"],
        "projects_dir": result.get("projects_dir"),
        "docs_dir": result.get("projects_dir") or result.get("docs_dir"),
        "raw_dir": result.get("projects_dir") or result.get("docs_dir"),
        "saved": result["saved"],
        "count": result["count"],
        "files": utils.list_ess_project_files(user_id),
        **_load_project_list_payload(user_id),
    }


@router.post("/projects")
async def upload_ess_project_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Legacy multipart path — the UI uses ``/projects/presign`` + ``/projects/complete``."""
    return await _upload_ess_project_multipart(request, file)


@router.post("/drawings/presign")
def ess_drawings_presign(body: EssDocsPresignRequest, request: Request) -> dict:
    """Return a short-lived S3 PUT URL for drawing document uploads."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    _assert_ess_doc_size(body.size)

    try:
        presign = utils.generate_ess_drawings_presigned_put(
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
        "drawings_dir": utils.ess_drawings_dir(user_id),
        "docs_dir": utils.ess_drawings_dir(user_id),
    }


@router.post("/drawings/complete")
def ess_drawings_complete(body: EssDocsCompleteRequest, request: Request) -> dict:
    """Confirm a presigned PUT and materialize the object into ``ess/drawings/``."""
    user_id = require_user_id(request)
    utils.ensure_user_ess_dir(user_id)
    _assert_ess_doc_size(body.size)

    try:
        utils._ensure_ess_on_path()
        from doc_list import sanitize_ess_filename

        safe_name = sanitize_ess_filename(body.file_name)
    except Exception:
        safe_name = Path(body.file_name).name

    expected_key = utils.ess_drawings_s3_key(safe_name, user_id=user_id)
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

    result = utils.materialize_ess_drawings_from_s3(
        key,
        safe_name,
        user_id=user_id,
        original_filename=body.original_filename or body.file_name,
    )
    if not result:
        raise HTTPException(
            status_code=500, detail="Failed to save file to ess/drawings"
        )

    return {
        "ok": True,
        "ess_dir": result["ess_dir"],
        "drawings_dir": result.get("drawings_dir"),
        "docs_dir": result.get("drawings_dir"),
        "raw_dir": result.get("drawings_dir"),
        "saved": result["saved"],
        "count": result.get("count", 1),
        "s3_key": key,
        "files": utils.list_ess_drawing_files(user_id),
        **_load_drawings_list_payload(user_id),
    }


async def _upload_ess_drawing_multipart(request: Request, file: UploadFile) -> dict:
    """Legacy multipart upload for drawing docs (small files only)."""
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
        result = utils.save_ess_drawing_upload(name, data, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"문서 저장 실패: {exc}",
        ) from exc

    return {
        "ess_dir": result["ess_dir"],
        "drawings_dir": result.get("drawings_dir"),
        "docs_dir": result.get("drawings_dir") or result.get("docs_dir"),
        "raw_dir": result.get("drawings_dir") or result.get("docs_dir"),
        "saved": result["saved"],
        "count": result["count"],
        "files": utils.list_ess_drawing_files(user_id),
        **_load_drawings_list_payload(user_id),
    }


@router.post("/drawings")
async def upload_ess_drawing_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Legacy multipart path — the UI uses ``/drawings/presign`` + ``/drawings/complete``."""
    return await _upload_ess_drawing_multipart(request, file)


@router.post("/docs/presign")
def ess_docs_presign_legacy(body: EssDocsPresignRequest, request: Request) -> dict:
    """Deprecated alias for ``POST /api/ess/regulations/presign``."""
    return ess_regulations_presign(body, request)


@router.post("/docs/complete")
def ess_docs_complete_legacy(body: EssDocsCompleteRequest, request: Request) -> dict:
    """Deprecated alias for ``POST /api/ess/regulations/complete``."""
    return ess_regulations_complete(body, request)


@router.post("/docs")
async def upload_ess_doc_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Deprecated alias for ``POST /api/ess/regulations``."""
    return await _upload_ess_doc_multipart(request, file)


@router.post("/raw")
async def upload_ess_raw_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Deprecated alias for ``POST /api/ess/regulations``."""
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
