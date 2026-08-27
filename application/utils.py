import logging
import sys
import json
import traceback
import boto3
import os
from urllib import parse
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("utils")

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')

workingDir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(workingDir, "config.json")
favorite_tools_path = os.path.join(workingDir, "favorite_tools.json")
# Local session root for per-user artifacts/skills (no S3 Files /mnt mount).
SESSION_STORAGE_DIR = os.environ.get(
    "SESSION_STORAGE_DIR",
    os.path.join(workingDir, ".session_storage"),
)
SKILLS_DIR = os.path.join(workingDir, "skills")


def sanitize_user_path_segment(user_id: str | None) -> str | None:
    """Return a safe single path segment for per-user workspace folders, or None."""
    if not user_id:
        return None
    raw = str(user_id).strip()
    # Never treat opaque signed session cookies as folder names.
    if raw.startswith("v1.") and raw.count(".") >= 2:
        logger.warning("Refusing signed session token as artifacts path segment")
        return None
    if len(raw) > 128:
        logger.warning("Refusing oversized user_id as artifacts path segment")
        return None
    # Collapse path separators so user_id cannot escape the intended prefix.
    segment = (
        raw
        .replace("/", "_")
        .replace("\\", "_")
        .replace("..", "_")
    )
    return segment or None


def get_user_artifacts_dir(user_id: str | None) -> str:
    """Absolute path to {SESSION_STORAGE_DIR}/{user_id}/artifacts (does not create)."""
    segment = sanitize_user_path_segment(user_id)
    if not segment:
        segment = "default"
    return os.path.join(SESSION_STORAGE_DIR, segment, "artifacts")


def ensure_user_artifacts_dir(user_id: str | None) -> str:
    """Create {SESSION_STORAGE_DIR}/{user_id}/artifacts if needed and return it."""
    segment = sanitize_user_path_segment(user_id)
    if not segment:
        raise ValueError(
            "Invalid user_id for artifacts path; expected a plain user id, "
            "not a signed session cookie"
        )
    artifacts_dir = os.path.join(SESSION_STORAGE_DIR, segment, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    logger.info("user artifacts dir ready: %s", artifacts_dir)
    return artifacts_dir


def get_user_skills_dir(user_id: str | None) -> str:
    """Absolute path to {SESSION_STORAGE_DIR}/{user_id}/skills (does not create)."""
    segment = sanitize_user_path_segment(user_id) or "default"
    return os.path.join(SESSION_STORAGE_DIR, segment, "skills")


def ensure_user_skills_dir(user_id: str | None) -> str:
    """Create {SESSION_STORAGE_DIR}/{user_id}/skills if needed and return it."""
    segment = sanitize_user_path_segment(user_id)
    if not segment:
        raise ValueError(
            "Invalid user_id for skills path; expected a plain user id, "
            "not a signed session cookie"
        )
    skills_dir = os.path.join(SESSION_STORAGE_DIR, segment, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    logger.info("user skills dir ready: %s", skills_dir)
    return skills_dir


def get_user_graph_dir(user_id: str | None) -> str:
    """Absolute path to {SESSION_STORAGE_DIR}/{user_id}/graph (does not create)."""
    segment = sanitize_user_path_segment(user_id)
    if not segment:
        segment = "default"
    return os.path.join(SESSION_STORAGE_DIR, segment, "graph")


def ensure_user_graph_dir(user_id: str | None) -> str:
    """Create session graph workspace: corpus/ + out/ (shared extract+publish).

    Returns the graph root: {SESSION_STORAGE_DIR}/{user_id}/graph
    """
    segment = sanitize_user_path_segment(user_id)
    if not segment:
        raise ValueError(
            "Invalid user_id for graph path; expected a plain user id, "
            "not a signed session cookie"
        )
    graph_dir = os.path.join(SESSION_STORAGE_DIR, segment, "graph")
    for name in ("corpus", "out"):
        os.makedirs(os.path.join(graph_dir, name), exist_ok=True)
    logger.info("user graph dir ready: %s", graph_dir)
    return graph_dir


def user_graph_html_path(user_id: str | None) -> str:
    """Published HTML: {SESSION_STORAGE_DIR}/{user_id}/graph/out/graph.html"""
    segment = sanitize_user_path_segment(user_id) or "default"
    return os.path.join(SESSION_STORAGE_DIR, segment, "graph", "out", "graph.html")


def get_user_ess_dir(user_id: str | None) -> str:
    """Per-user ESS root: ``{SESSION_STORAGE_DIR}/{user_id}/ess``."""
    segment = sanitize_user_path_segment(user_id)
    if not segment:
        segment = "default"
    return os.path.join(SESSION_STORAGE_DIR, segment, "ess")


def _ensure_ess_on_path() -> str:
    """Put ``ess-project/ess`` on ``sys.path`` so ``doc_list`` is importable."""
    ess_pkg = os.path.join(os.path.dirname(workingDir), "ess")
    if ess_pkg not in sys.path:
        sys.path.insert(0, ess_pkg)
    return ess_pkg


def ensure_user_ess_dir(user_id: str | None) -> str:
    """Create ``{user}/ess``, ``regulations/``, ``projects/``, ``out/``, … and return ESS root."""
    segment = sanitize_user_path_segment(user_id)
    if not segment:
        raise ValueError(
            "Invalid user_id for ess path; expected a plain user id, "
            "not a signed session cookie"
        )
    ess_dir = os.path.join(SESSION_STORAGE_DIR, segment, "ess")
    for name in (
        "",
        "regulations",
        "projects",
        "test_cases",
        "out",
        os.path.join("out", "converted"),
        os.path.join("out", "converted", ".pdf_pages"),
    ):
        os.makedirs(os.path.join(ess_dir, name) if name else ess_dir, exist_ok=True)
    try:
        _ensure_ess_on_path()
        from doc_list import (
            PROJECTS,
            TEST_CASES,
            doc_list_path,
            empty_doc_list,
            migrate_raw_to_docs,
            save_doc_list,
            sync_doc_list_with_filesystem,
        )

        migrate_raw_to_docs(ess_dir)
        if not doc_list_path(ess_dir).is_file():
            docs = os.path.join(ess_dir, "regulations")
            has_files = os.path.isdir(docs) and any(
                os.path.isfile(os.path.join(docs, n)) for n in os.listdir(docs)
            )
            if has_files:
                sync_doc_list_with_filesystem(ess_dir, user_id=segment)
            else:
                save_doc_list(ess_dir, empty_doc_list(user_id=segment))
        if not doc_list_path(ess_dir, PROJECTS).is_file():
            projects = os.path.join(ess_dir, "projects")
            has_projects = os.path.isdir(projects) and any(
                os.path.isfile(os.path.join(projects, n)) for n in os.listdir(projects)
            )
            if has_projects:
                sync_doc_list_with_filesystem(
                    ess_dir, user_id=segment, registry=PROJECTS
                )
            else:
                save_doc_list(
                    ess_dir, empty_doc_list(user_id=segment), registry=PROJECTS
                )
        if not doc_list_path(ess_dir, TEST_CASES).is_file():
            test_cases = os.path.join(ess_dir, "test_cases")
            has_tc = os.path.isdir(test_cases) and any(
                os.path.isfile(os.path.join(test_cases, n)) for n in os.listdir(test_cases)
            )
            if has_tc:
                sync_doc_list_with_filesystem(
                    ess_dir, user_id=segment, registry=TEST_CASES
                )
            else:
                save_doc_list(
                    ess_dir, empty_doc_list(user_id=segment), registry=TEST_CASES
                )
    except Exception:
        logger.debug("ess doc_list ensure skipped", exc_info=True)
    logger.debug("user ess dir ready: %s", ess_dir)
    return ess_dir


def ess_converted_dir(user_id: str | None = None) -> str:
    """``{SESSION_STORAGE}/{user}/ess/out/converted``."""
    return os.path.join(ess_out_dir(user_id), "converted")


def ess_docs_dir(user_id: str | None = None) -> str:
    """``{SESSION_STORAGE}/{user}/ess/regulations`` (legacy: ``docs``, ``raw``)."""
    ess = get_user_ess_dir(user_id)
    docs = os.path.join(ess, "regulations")
    legacy_docs = os.path.join(ess, "docs")
    legacy_raw = os.path.join(ess, "raw")
    if not os.path.isdir(docs) and (
        os.path.isdir(legacy_docs) or os.path.isdir(legacy_raw)
    ):
        try:
            _ensure_ess_on_path()
            from doc_list import migrate_raw_to_docs

            migrate_raw_to_docs(ess)
        except Exception:
            pass
    return docs


def ess_raw_dir(user_id: str | None = None) -> str:
    """Deprecated alias for :func:`ess_docs_dir`."""
    return ess_docs_dir(user_id)


def ess_out_dir(user_id: str | None = None) -> str:
    return os.path.join(get_user_ess_dir(user_id), "out")


def ess_doc_list_path(user_id: str | None = None) -> str:
    return os.path.join(get_user_ess_dir(user_id), "regulations_list.json")


def ess_projects_dir(user_id: str | None = None) -> str:
    """``{SESSION_STORAGE}/{user}/ess/projects``."""
    return os.path.join(get_user_ess_dir(user_id), "projects")


def ess_project_list_path(user_id: str | None = None) -> str:
    return os.path.join(get_user_ess_dir(user_id), "project_list.json")


def ess_test_cases_dir(user_id: str | None = None) -> str:
    """``{SESSION_STORAGE}/{user}/ess/test_cases``."""
    return os.path.join(get_user_ess_dir(user_id), "test_cases")


def ess_test_cases_list_path(user_id: str | None = None) -> str:
    return os.path.join(get_user_ess_dir(user_id), "test_cases_list.json")


def _ess_docs_dest_path(docs_dir: str, filename: str) -> tuple[str, str, str]:
    """Return ``(dest_path, sanitized_name, original_basename)``.

    Sanitizes at upload time (spaces → ``_``, unsafe chars stripped).
    """
    original = os.path.basename((filename or "").strip()) or "upload.bin"
    original = original.replace("\x00", "_") or "upload.bin"
    try:
        _ensure_ess_on_path()
        from doc_list import sanitize_ess_filename

        safe = sanitize_ess_filename(original)
    except Exception:
        safe = original.replace(" ", "_")
        safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in safe)
        while "__" in safe:
            safe = safe.replace("__", "_")
        stem, ext = os.path.splitext(safe)
        safe = f"{stem.strip('._-') or 'document'}{ext.lower()}"
    return os.path.join(docs_dir, safe), safe, original


def save_ess_doc_upload(
    filename: str,
    data: bytes,
    *,
    user_id: str | None = None,
) -> dict[str, object]:
    """Sanitize filename, write into ``{user}/ess/regulations``, update regulations_list."""
    if data is None or len(data) == 0:
        raise ValueError("저장할 파일이 없습니다.")

    ess = ensure_user_ess_dir(user_id)
    docs = os.path.join(ess, "regulations")
    os.makedirs(docs, exist_ok=True)
    dest, safe_name, original_name = _ess_docs_dest_path(docs, filename)
    overwritten = os.path.isfile(dest)
    with open(dest, "wb") as f:
        f.write(data)

    segment = sanitize_user_path_segment(user_id) or "default"
    try:
        _ensure_ess_on_path()
        from doc_list import upsert_document

        upsert_document(
            ess,
            filename=safe_name,
            source_path=os.path.abspath(dest),
            bytes_size=len(data),
            status="uploaded",
            user_id=segment,
            extra={
                "original_filename": original_name,
                "sanitized": original_name != safe_name,
            },
        )
    except Exception:
        logger.exception("Failed to update ess doc_list after upload")

    logger.info(
        "ess docs upload user=%s → %s (original=%s, %s bytes%s)",
        segment,
        dest,
        original_name,
        len(data),
        ", overwrite" if overwritten else "",
    )
    return {
        "ess_dir": ess,
        "docs_dir": docs,
        "raw_dir": docs,  # backward-compatible key
        "saved": {
            "name": safe_name,
            "original_filename": original_name,
            "sanitized": original_name != safe_name,
            "path": dest,
            "bytes": len(data),
            "overwritten": overwritten,
        },
        "count": 1,
        "doc_list": ess_doc_list_path(user_id),
    }


def save_ess_raw_upload(
    filename: str,
    data: bytes,
    *,
    user_id: str | None = None,
) -> dict[str, object]:
    """Deprecated alias for :func:`save_ess_doc_upload`."""
    return save_ess_doc_upload(filename, data, user_id=user_id)


def save_ess_project_upload(
    filename: str,
    data: bytes,
    *,
    user_id: str | None = None,
) -> dict[str, object]:
    """Sanitize filename, write into ``{user}/ess/projects``, update project_list."""
    if data is None or len(data) == 0:
        raise ValueError("저장할 파일이 없습니다.")

    ess = ensure_user_ess_dir(user_id)
    projects = os.path.join(ess, "projects")
    os.makedirs(projects, exist_ok=True)
    dest, safe_name, original_name = _ess_docs_dest_path(projects, filename)
    overwritten = os.path.isfile(dest)
    with open(dest, "wb") as f:
        f.write(data)

    segment = sanitize_user_path_segment(user_id) or "default"
    try:
        _ensure_ess_on_path()
        from doc_list import PROJECTS, upsert_document

        upsert_document(
            ess,
            filename=safe_name,
            source_path=os.path.abspath(dest),
            bytes_size=len(data),
            status="uploaded",
            user_id=segment,
            extra={
                "original_filename": original_name,
                "sanitized": original_name != safe_name,
            },
            registry=PROJECTS,
        )
    except Exception:
        logger.exception("Failed to update ess project_list after upload")

    logger.info(
        "ess projects upload user=%s → %s (original=%s, %s bytes%s)",
        segment,
        dest,
        original_name,
        len(data),
        ", overwrite" if overwritten else "",
    )
    return {
        "ess_dir": ess,
        "projects_dir": projects,
        "docs_dir": projects,
        "raw_dir": projects,
        "saved": {
            "name": safe_name,
            "original_filename": original_name,
            "sanitized": original_name != safe_name,
            "path": dest,
            "bytes": len(data),
            "overwritten": overwritten,
        },
        "count": 1,
        "doc_list": ess_project_list_path(user_id),
        "project_list": ess_project_list_path(user_id),
    }


def save_ess_testcase(
    xlsx_path: str,
    *,
    user_id: str | None = None,
    cases_json_path: str | None = None,
    title: str | None = None,
    standard: str | None = None,
    source_md: str | None = None,
    rows: int | None = None,
    filename: str | None = None,
) -> dict[str, object]:
    """Copy a generated test-case xlsx into ``{user}/ess/test_cases`` and update list.

    Also copies optional cases JSON as ``{stem}.json`` sidecar and upserts
    ``test_cases_list.json`` (same shape as ``project_list.json``).
    """
    src = os.path.abspath(os.path.expanduser(xlsx_path or ""))
    if not src or not os.path.isfile(src):
        raise ValueError(f"테스트케이스 파일이 없습니다: {xlsx_path}")

    ess = ensure_user_ess_dir(user_id)
    tc_dir = os.path.join(ess, "test_cases")
    os.makedirs(tc_dir, exist_ok=True)

    preferred = filename or os.path.basename(src)
    dest, safe_name, original_name = _ess_docs_dest_path(tc_dir, preferred)
    if not safe_name.lower().endswith(".xlsx"):
        safe_name = f"{os.path.splitext(safe_name)[0]}.xlsx"
        dest = os.path.join(tc_dir, safe_name)
    overwritten = os.path.isfile(dest)

    with open(src, "rb") as f:
        data = f.read()
    if not data:
        raise ValueError("저장할 파일이 비어 있습니다.")
    with open(dest, "wb") as f:
        f.write(data)

    stem = os.path.splitext(safe_name)[0]
    json_dest: str | None = None
    meta_title = title
    meta_standard = standard
    meta_source_md = source_md
    meta_rows = rows

    cases_src = cases_json_path
    if cases_src:
        cases_src = os.path.abspath(os.path.expanduser(cases_src))
    if cases_src and os.path.isfile(cases_src):
        try:
            import json as _json

            with open(cases_src, encoding="utf-8") as cf:
                payload = _json.load(cf)
            if isinstance(payload, dict):
                meta_title = meta_title or payload.get("title")
                meta_standard = meta_standard or payload.get("standard")
                meta_source_md = meta_source_md or payload.get("source_md")
                cases = payload.get("cases")
                if meta_rows is None and isinstance(cases, list):
                    meta_rows = len(cases)
        except Exception:
            logger.debug("cases json metadata parse skipped", exc_info=True)
        json_dest = os.path.join(tc_dir, f"{stem}.json")
        try:
            with open(cases_src, "rb") as f:
                json_bytes = f.read()
            with open(json_dest, "wb") as f:
                f.write(json_bytes)
        except OSError:
            logger.exception("Failed to copy cases json sidecar")
            json_dest = None

    segment = sanitize_user_path_segment(user_id) or "default"
    extra: dict[str, object] = {
        "original_filename": original_name,
        "sanitized": original_name != safe_name,
    }
    if meta_title:
        extra["title"] = str(meta_title)
    if meta_standard:
        extra["standard"] = str(meta_standard)
    if meta_source_md:
        extra["source_md"] = str(meta_source_md)
    if meta_rows is not None:
        extra["rows"] = int(meta_rows)

    try:
        _ensure_ess_on_path()
        from doc_list import TEST_CASES, upsert_document

        upsert_document(
            ess,
            filename=safe_name,
            source_path=os.path.abspath(dest),
            bytes_size=len(data),
            status="saved",
            user_id=segment,
            json_path=os.path.abspath(json_dest) if json_dest else None,
            extra=extra,
            registry=TEST_CASES,
        )
    except Exception:
        logger.exception("Failed to update ess test_cases_list after save")

    logger.info(
        "ess test_cases save user=%s → %s (original=%s, %s bytes%s)",
        segment,
        dest,
        original_name,
        len(data),
        ", overwrite" if overwritten else "",
    )
    return {
        "ess_dir": ess,
        "test_cases_dir": tc_dir,
        "saved": {
            "name": safe_name,
            "original_filename": original_name,
            "sanitized": original_name != safe_name,
            "path": dest,
            "json_path": json_dest,
            "bytes": len(data),
            "overwritten": overwritten,
            "title": meta_title,
            "standard": meta_standard,
            "source_md": meta_source_md,
            "rows": meta_rows,
        },
        "count": 1,
        "test_cases_list": ess_test_cases_list_path(user_id),
    }


def list_ess_doc_files(user_id: str | None = None) -> list[dict[str, object]]:
    """List files currently under the user's ``ess/regulations``."""
    docs = ess_docs_dir(user_id)
    if not os.path.isdir(docs):
        return []
    out: list[dict[str, object]] = []
    try:
        names = sorted(os.listdir(docs))
    except OSError:
        return []
    for name in names:
        path = os.path.join(docs, name)
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        out.append({"name": name, "path": path, "bytes": size, "mtime": mtime})
    return out


def list_ess_project_files(user_id: str | None = None) -> list[dict[str, object]]:
    """List files currently under the user's ``ess/projects``."""
    projects = ess_projects_dir(user_id)
    if not os.path.isdir(projects):
        return []
    out: list[dict[str, object]] = []
    try:
        names = sorted(os.listdir(projects))
    except OSError:
        return []
    for name in names:
        path = os.path.join(projects, name)
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        out.append({"name": name, "path": path, "bytes": size, "mtime": mtime})
    return out


def list_ess_raw_files(user_id: str | None = None) -> list[dict[str, object]]:
    """Deprecated alias for :func:`list_ess_doc_files`."""
    return list_ess_doc_files(user_id)


def is_ess_foundation_model_parser_enabled(user_id: str | None) -> bool:
    """True when ESS Foundation Model Parser is on (default True)."""
    return bool(
        load_user_settings(user_id).get(
            "ess_foundation_model_parser_enabled", True
        )
    )


def set_ess_foundation_model_parser_enabled(
    enabled: bool, *, user_id: str | None = None
) -> bool:
    settings = save_user_settings(
        user_id, ess_foundation_model_parser_enabled=bool(enabled)
    )
    return bool(settings.get("ess_foundation_model_parser_enabled", True))


GRAPH_PATTERNS = ("pattern1", "pattern2", "pattern3")
DEFAULT_GRAPH_PATTERN = "pattern1"

_DEFAULT_USER_SETTINGS: dict[str, object] = {
    "knowledge_graph_enabled": True,
    "graph_pattern": DEFAULT_GRAPH_PATTERN,
    # ESS Configure: Foundation Model Parser (default On).
    "ess_foundation_model_parser_enabled": True,
}


def normalize_graph_pattern(value: object | None) -> str:
    raw = str(value or "").strip().lower().replace(" ", "").replace("_", "")
    aliases = {
        "pattern1": "pattern1",
        "p1": "pattern1",
        "1": "pattern1",
        "forceatlas": "pattern1",
        "pattern2": "pattern2",
        "p2": "pattern2",
        "2": "pattern2",
        "neo4j": "pattern2",
        "neo4jexplore": "pattern2",
        "pattern3": "pattern3",
        "p3": "pattern3",
        "3": "pattern3",
        "holistic": "pattern3",
        "holisticview": "pattern3",
    }
    return aliases.get(raw, DEFAULT_GRAPH_PATTERN)



def get_user_db_path(user_id: str | None) -> str:
    """Durable per-user tasks/messages DB: {SESSION_STORAGE_DIR}/{user_id}/{user_id}.db."""
    segment = sanitize_user_path_segment(user_id) or "default"
    return os.path.join(SESSION_STORAGE_DIR, segment, f"{segment}.db")


def get_user_settings_path(user_id: str | None) -> str:
    """Absolute path to {SESSION_STORAGE_DIR}/{user_id}/settings.json (does not create)."""
    segment = sanitize_user_path_segment(user_id) or "default"
    return os.path.join(SESSION_STORAGE_DIR, segment, "settings.json")


def _normalize_string_list(value: object) -> list[str]:
    """Return a cleaned list of non-empty strings (stable order, no duplicates)."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def load_user_settings(user_id: str | None) -> dict[str, object]:
    """Load per-user UI/feature settings. Missing file → defaults (KG on).

    ``skills`` / ``mcp_servers`` are omitted until the user has saved them so
    callers can fall back to favorite_tools.json.
    """
    settings = dict(_DEFAULT_USER_SETTINGS)
    path = get_user_settings_path(user_id)
    if not os.path.isfile(path):
        return settings
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            if "knowledge_graph_enabled" in raw:
                settings["knowledge_graph_enabled"] = bool(raw["knowledge_graph_enabled"])
            if "graph_pattern" in raw:
                settings["graph_pattern"] = normalize_graph_pattern(raw.get("graph_pattern"))
            if "ess_foundation_model_parser_enabled" in raw:
                settings["ess_foundation_model_parser_enabled"] = bool(
                    raw["ess_foundation_model_parser_enabled"]
                )
            if "skills" in raw:
                settings["skills"] = _normalize_string_list(raw.get("skills"))
            if "mcp_servers" in raw:
                settings["mcp_servers"] = _normalize_string_list(raw.get("mcp_servers"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load user settings %s: %s", path, e)
    return settings


def save_user_settings(user_id: str | None, **updates: object) -> dict[str, object]:
    """Merge updates into per-user settings.json and return the full settings."""
    segment = sanitize_user_path_segment(user_id)
    if not segment:
        raise ValueError(
            "Invalid user_id for settings path; expected a plain user id, "
            "not a signed session cookie"
        )
    user_dir = os.path.join(SESSION_STORAGE_DIR, segment)
    os.makedirs(user_dir, exist_ok=True)
    settings = load_user_settings(user_id)
    for key, value in updates.items():
        if key == "knowledge_graph_enabled":
            settings[key] = bool(value)
        elif key == "graph_pattern":
            settings[key] = normalize_graph_pattern(value)
        elif key == "ess_foundation_model_parser_enabled":
            settings[key] = bool(value)
        elif key == "skills":
            settings[key] = _normalize_string_list(value)
        elif key == "mcp_servers":
            settings[key] = _normalize_string_list(value)
    path = get_user_settings_path(user_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    logger.info("user settings saved: %s -> %s", path, settings)
    return settings


def is_knowledge_graph_enabled(user_id: str | None) -> bool:
    """True when Knowledge Graph feature is on (default)."""
    return bool(load_user_settings(user_id).get("knowledge_graph_enabled", True))



def is_hybrid_graph_search_enabled() -> bool:
    """True when config.json hybrid_graph_search is enable (embedding vector search)."""
    cfg = load_config() or {}
    raw = str(cfg.get("hybrid_graph_search") or "").strip().lower()
    return raw in {"enable", "enabled", "on", "true", "1", "yes"}


def get_graph_pattern(user_id: str | None) -> str:
    """Selected Knowledge Graph HTML pattern (pattern1|pattern2|pattern3)."""
    return normalize_graph_pattern(
        load_user_settings(user_id).get("graph_pattern", DEFAULT_GRAPH_PATTERN)
    )


def get_user_skills_list_path(user_id: str | None) -> str:
    """Absolute path to {SESSION_STORAGE_DIR}/{user_id}/skills.list (does not create)."""
    segment = sanitize_user_path_segment(user_id) or "default"
    return os.path.join(SESSION_STORAGE_DIR, segment, "skills.list")


def _list_skill_dir_names(skills_dir: str) -> list[str]:
    """Return subdirectory names that contain SKILL.md."""
    if not os.path.isdir(skills_dir):
        return []
    names: list[str] = []
    try:
        entries = sorted(os.listdir(skills_dir))
    except OSError as e:
        logger.warning("Failed to list skills directory %s: %s", skills_dir, e)
        return []
    for entry in entries:
        if os.path.isfile(os.path.join(skills_dir, entry, "SKILL.md")):
            names.append(entry)
    return names


def _load_skills_list_file(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    except FileNotFoundError:
        return []
    except OSError as e:
        logger.warning("Failed to read skills.list %s: %s", path, e)
        return []


def _seed_skill_names(user_id: str | None) -> list[str]:
    """Builtin application/skills.list + skill-creator dirs under the user skills path."""
    default_path = os.path.join(workingDir, "skills.list")
    builtin = _load_skills_list_file(default_path)
    user_skills = _list_skill_dir_names(get_user_skills_dir(user_id))
    merged: list[str] = []
    seen: set[str] = set()
    for name in builtin + user_skills:
        if name not in seen:
            merged.append(name)
            seen.add(name)
    return merged


def write_user_skills_list(user_id: str | None, names: list[str] | None = None) -> str:
    """Write {SESSION_STORAGE_DIR}/{user_id}/skills.list and return its path."""
    ensure_user_skills_dir(user_id)
    path = get_user_skills_list_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged = names if names is not None else _seed_skill_names(user_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(merged) + ("\n" if merged else ""))
    logger.info(
        "wrote user skills.list (%d skills) -> %s",
        len(merged),
        path,
    )
    return path


def update_user_skills_list(user_id: str | None) -> str:
    """Rewrite per-user skills.list from application/skills.list + user skills dir."""
    return write_user_skills_list(user_id)


def _builtin_skill_exists(name: str) -> bool:
    return os.path.isfile(os.path.join(workingDir, "skills", name, "SKILL.md"))


def _user_skill_exists(user_id: str | None, name: str) -> bool:
    return os.path.isfile(
        os.path.join(get_user_skills_dir(user_id), name, "SKILL.md")
    )


def ensure_user_skills_list(user_id: str | None) -> str:
    """Use {SESSION_STORAGE_DIR}/{user_id}/skills.list; create it if missing.

    When the file already exists, keep user ordering/custom entries, but:
    - append new builtin names from application/skills.list
    - append newly discovered skill-creator dirs under ``{user_id}/skills/``
    - drop entries whose SKILL.md no longer exists in builtin or user skills
    """
    ensure_user_skills_dir(user_id)
    path = get_user_skills_list_path(user_id)
    if not os.path.isfile(path):
        return write_user_skills_list(user_id)

    existing = _load_skills_list_file(path)
    kept = [
        name
        for name in existing
        if _builtin_skill_exists(name) or _user_skill_exists(user_id, name)
    ]
    seen = set(kept)
    default_path = os.path.join(workingDir, "skills.list")
    candidates = _load_skills_list_file(default_path) + _list_skill_dir_names(
        get_user_skills_dir(user_id)
    )
    appended = [name for name in candidates if name not in seen]
    updated = kept + appended
    if updated != existing:
        return write_user_skills_list(user_id, updated)
    logger.info(
        "using existing user skills.list (%d skills) -> %s",
        len(existing),
        path,
    )
    return path


def load_config():
    config = None

    try: 
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        config = {}

        projectName = "agent-skills"
        session = boto3.Session()
        region = session.region_name
        config['region'] = region
        config['projectName'] = projectName
        
        sts = boto3.client("sts")
        response = sts.get_caller_identity()
        accountId = response["Account"]
        config['accountId'] = accountId
        config['s3_bucket'] = f'storage-for-rag-project-{accountId}-{region}'
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)    
    return config


def load_favorite_tools() -> dict[str, list[str]]:
    """Load favorite tool defaults for initial selections."""
    fallback = {"MCP": [], "SKILL": []}
    try:
        with open(favorite_tools_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning("favorite_tools.json not found: %s", favorite_tools_path)
        return fallback
    except Exception as e:
        logger.warning("Failed to load favorite_tools.json: %s", e)
        return fallback

    if not isinstance(data, dict):
        return fallback

    favorites: dict[str, list[str]] = {}
    for key in ("MCP", "SKILL"):
        values = data.get(key, [])
        if isinstance(values, list):
            favorites[key] = [v for v in values if isinstance(v, str) and v.strip()]
        else:
            favorites[key] = []
    return favorites


def save_favorite_tools(*, skills: list[str] | None = None, mcp_servers: list[str] | None = None) -> dict[str, list[str]]:
    """Persist favorite tool defaults in favorite_tools.json."""
    favorites = load_favorite_tools()
    if skills is not None:
        favorites["SKILL"] = [v for v in skills if isinstance(v, str) and v.strip()]
    if mcp_servers is not None:
        favorites["MCP"] = [v for v in mcp_servers if isinstance(v, str) and v.strip()]

    with open(favorite_tools_path, "w", encoding="utf-8") as f:
        json.dump(favorites, f, ensure_ascii=False, indent=2)
    return favorites


def get_initial_tool_defaults() -> tuple[list[str], list[str]]:
    """Return initial skill/MCP defaults from favorite_tools.json."""
    favorite_tools = load_favorite_tools()
    default_skills = favorite_tools.get("SKILL") or []
    default_mcp_servers = favorite_tools.get("MCP") or []
    return default_skills, default_mcp_servers


def get_user_tool_defaults(user_id: str | None) -> tuple[list[str], list[str]]:
    """Per-user skill/MCP defaults from settings.json, else favorite_tools.json."""
    fav_skills, fav_mcp = get_initial_tool_defaults()
    settings = load_user_settings(user_id)
    skills = settings.get("skills")
    mcp_servers = settings.get("mcp_servers")
    return (
        list(skills) if isinstance(skills, list) else fav_skills,
        list(mcp_servers) if isinstance(mcp_servers, list) else fav_mcp,
    )


def save_user_tool_defaults(
    user_id: str | None,
    *,
    skills: list[str] | None = None,
    mcp_servers: list[str] | None = None,
) -> dict[str, object]:
    """Persist the user's last skill/MCP selection into settings.json."""
    updates: dict[str, object] = {}
    if skills is not None:
        updates["skills"] = skills
    if mcp_servers is not None:
        updates["mcp_servers"] = mcp_servers
    if not updates:
        return load_user_settings(user_id)
    return save_user_settings(user_id, **updates)

config = load_config()

accountId = config.get('accountId')
if not accountId:
    sts = boto3.client("sts")
    response = sts.get_caller_identity()
    accountId = response["Account"]
    config['accountId'] = accountId
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

bedrock_region = config.get('region', 'us-west-2')
logger.info(f"bedrock_region: {bedrock_region}")
projectName = config.get('projectName', 'mop')
logger.info(f"projectName: {projectName}")


def persist_config_updates(updates):
    """Merge values fetched from Secrets Manager into config and write config.json."""
    global config
    if not updates:
        return
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        s = value.strip() if isinstance(value, str) else str(value)
        if not s:
            continue
        if config.get(key) != s:
            config[key] = s
            changed = True
    if not changed:
        return
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(
            "Saved Secrets Manager values to config.json: %s",
            ", ".join(str(k) for k in updates if updates.get(k)),
        )
    except Exception as e:
        logger.warning("Failed to write config.json: %s", e)


def get_contents_type(file_name):
    lower = file_name.lower()
    if lower.endswith((".jpg", ".jpeg")):
        content_type = "image/jpeg"
    elif lower.endswith(".png"):
        content_type = "image/png"
    elif lower.endswith(".webp"):
        content_type = "image/webp"
    elif lower.endswith(".gif"):
        content_type = "image/gif"
    elif lower.endswith(".pdf"):
        content_type = "application/pdf"
    elif lower.endswith(".txt"):
        content_type = "text/plain"
    elif lower.endswith(".csv"):
        content_type = "text/csv"
    elif lower.endswith((".ppt", ".pptx")):
        content_type = "application/vnd.ms-powerpoint"
    elif lower.endswith((".doc", ".docx")):
        content_type = "application/msword"
    elif lower.endswith((".xls", ".xlsx")):
        content_type = "application/vnd.ms-excel"
    elif lower.endswith(".py"):
        content_type = "text/x-python"
    elif lower.endswith(".js"):
        content_type = "application/javascript"
    elif lower.endswith(".md"):
        content_type = "text/markdown"
    elif lower.endswith((".html", ".htm")):
        content_type = "text/html; charset=utf-8"
    else:
        content_type = "no info"
    return content_type

def load_mcp_env():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_env_path = os.path.join(script_dir, "mcp.env")
    
    with open(mcp_env_path, "r", encoding="utf-8") as f:
        mcp_env = json.load(f)
    return mcp_env

def save_mcp_env(mcp_env):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_env_path = os.path.join(script_dir, "mcp.env")
    
    with open(mcp_env_path, "w", encoding="utf-8") as f:
        json.dump(mcp_env, f)

# api key to get information in agent
if aws_access_key and aws_secret_key:
    secretsmanager = boto3.client(
        service_name='secretsmanager',
        region_name=bedrock_region,
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        aws_session_token=aws_session_token,
    )
else:
    secretsmanager = boto3.client(
        service_name='secretsmanager',
        region_name=bedrock_region
    )

# Notion API key: prefer config.json, else Secrets Manager
notion_api_key = (config.get("notion_api_key") or "").strip()
if notion_api_key:
    os.environ["NOTION_API_KEY"] = notion_api_key
else:
    try:
        get_notion_api_secret = secretsmanager.get_secret_value(
            SecretId="notionapikey"
        )
        secret = json.loads(get_notion_api_secret["SecretString"])

        if "notion_api_key" in secret:
            notion_api_key = (secret["notion_api_key"] or "").strip()

        if notion_api_key:
            os.environ["NOTION_API_KEY"] = notion_api_key
            persist_config_updates({"notion_api_key": notion_api_key})
        else:
            logger.info("notion_api_key is required.")
    except Exception as e:
        logger.info(f"Notion credential is required: {e}")
        pass

# Telegram API key: prefer config.json, else Secrets Manager
telegram_api_key = (config.get("telegram_api_key") or "").strip()
if telegram_api_key:
    os.environ["TELEGRAM_API_KEY"] = telegram_api_key
else:
    try:
        get_telegram_api_secret = secretsmanager.get_secret_value(
            SecretId="telegramapikey"
        )
        secret = json.loads(get_telegram_api_secret["SecretString"])

        if "telegram_api_key" in secret:
            telegram_api_key = (secret["telegram_api_key"] or "").strip()

        if telegram_api_key:
            os.environ["TELEGRAM_API_KEY"] = telegram_api_key
            persist_config_updates({"telegram_api_key": telegram_api_key})
        else:
            logger.info("telegram_api_key is required.")
    except Exception as e:
        logger.info(f"Telegram credential is required: {e}")
        pass

# Discord bot token: prefer config.json, else Secrets Manager
discord_bot_token = (config.get("discord_bot_token") or "").strip()
if discord_bot_token:
    os.environ["DISCORD_BOT_TOKEN"] = discord_bot_token
else:
    try:
        get_discord_secret = secretsmanager.get_secret_value(
            SecretId="discordapikey"
        )
        secret = json.loads(get_discord_secret["SecretString"])

        if "discord_bot_token" in secret:
            discord_bot_token = (secret["discord_bot_token"] or "").strip()

        if discord_bot_token:
            os.environ["DISCORD_BOT_TOKEN"] = discord_bot_token
            persist_config_updates({"discord_bot_token": discord_bot_token})
        else:
            logger.info("discord_bot_token is required.")
    except Exception as e:
        logger.info(f"Discord credential is required: {e}")
        pass

# Slack: prefer config.json; any missing fields are filled from Secrets Manager
slack_bot_token = (config.get("slack_bot_token") or "").strip()
slack_team_id = (config.get("slack_team_id") or "").strip()
slack_token_from_config = bool(slack_bot_token)
slack_team_from_config = bool(slack_team_id)
if slack_bot_token:
    os.environ["SLACK_BOT_TOKEN"] = slack_bot_token
if slack_team_id:
    os.environ["SLACK_TEAM_ID"] = slack_team_id

if not slack_bot_token or not slack_team_id:
    try:
        get_slack_secret = secretsmanager.get_secret_value(
            SecretId="slackapikey"
        )
        secret = json.loads(get_slack_secret["SecretString"])
        if not slack_bot_token:
            slack_bot_token = (secret.get("slack_bot_token") or "").strip()
            if slack_bot_token:
                os.environ["SLACK_BOT_TOKEN"] = slack_bot_token
        if not slack_team_id:
            slack_team_id = (secret.get("slack_team_id") or "").strip()
            if slack_team_id:
                os.environ["SLACK_TEAM_ID"] = slack_team_id
        slack_persist = {}
        if not slack_token_from_config and slack_bot_token:
            slack_persist["slack_bot_token"] = slack_bot_token
        if not slack_team_from_config and slack_team_id:
            slack_persist["slack_team_id"] = slack_team_id
        persist_config_updates(slack_persist)
    except Exception as e:
        logger.info(f"Slack credential is required: {e}")
        pass

def sanitize_data_source_name(name):
    """
    Sanitize a name to comply with AWS Bedrock data source name pattern:
    ([0-9a-zA-Z][_-]?){1,100}
    - Pattern means: alphanumeric, optionally followed by underscore or hyphen, repeated 1-100 times
    - Cannot have consecutive underscores or hyphens
    - Must start with alphanumeric
    """
    import re
    # Remove any characters that are not alphanumeric, underscore, or hyphen
    sanitized = re.sub(r'[^0-9a-zA-Z_-]', '', name)
    
    # Replace consecutive underscores/hyphens with single hyphen
    # This ensures the pattern [0-9a-zA-Z][_-]? is followed correctly
    sanitized = re.sub(r'[_-]{2,}', '-', sanitized)
    
    # Ensure it starts with alphanumeric character
    if sanitized and not sanitized[0].isalnum():
        sanitized = 'ds' + sanitized
    
    # Remove trailing hyphens/underscores (they must be followed by alphanumeric per pattern)
    sanitized = sanitized.rstrip('_-')
    
    # Ensure it's not empty and limit to 100 characters
    if not sanitized:
        sanitized = 'datasource'
    
    # Final validation: ensure it matches the pattern exactly
    pattern = re.compile(r'^([0-9a-zA-Z][_-]?){1,100}$')
    if not pattern.match(sanitized):
        # If still doesn't match, create a safe default name
        # Use project name or create a simple alphanumeric name
        safe_name = re.sub(r'[^0-9a-zA-Z]', '', name.lower())
        if not safe_name:
            safe_name = 'datasource'
        sanitized = safe_name[:100]
    
    return sanitized[:100]

knowledge_base_id = config.get('knowledge_base_id')
data_source_id = config.get('data_source_id')
region = config.get('region', 'us-west-2')
s3_bucket = config.get('s3_bucket', f'storage-for-rag-project-{accountId}-{region}')
sharing_url = config.get('sharing_url', '')

def update_sharing_url():
    """Look up CloudFront distribution domain for this project and save as sharing_url."""
    try:
        cf_client = boto3.client('cloudfront', region_name=region)
        paginator = cf_client.get_paginator('list_distributions')
        target_origin_id = f"s3-{projectName}"

        for page in paginator.paginate():
            dist_list = page.get('DistributionList', {})
            for dist in dist_list.get('Items', []):
                origins = dist.get('Origins', {}).get('Items', [])
                for origin in origins:
                    if origin['Id'] == target_origin_id:
                        domain = dist['DomainName']
                        url = f"https://{domain}"
                        logger.info(f"sharing_url found: {url}")
                        config['sharing_url'] = url
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config, f, indent=2)
                        return url
        logger.warning(f"CloudFront distribution with origin '{target_origin_id}' not found")
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"Failed to look up sharing_url: {err_msg}")
    return ''

if not sharing_url:
    sharing_url = update_sharing_url()

def update_rag_info():
    knowledge_base_id = None
    data_source_id = None
    try: 
        client = boto3.client(
            service_name='bedrock-agent',
            region_name=region
        )

        response = client.list_knowledge_bases(
            maxResults=50
        )
        logger.info(f"(list_knowledge_bases) response: {response}")
        
        knowledge_base_name = config.get("knowledge_base_name") or config.get(
            "projectName", projectName
        )
        if "knowledgeBaseSummaries" in response:
            summaries = response["knowledgeBaseSummaries"]
            for summary in summaries:
                if summary["name"] == knowledge_base_name:
                    knowledge_base_id = summary["knowledgeBaseId"]
                    logger.info(f"knowledge_base_id: {knowledge_base_id}")

        if not knowledge_base_id:
            logger.warning(f"Knowledge Base not found for project: {knowledge_base_name}")
            return knowledge_base_id, data_source_id

        if not s3_bucket:
            logger.warning(f"s3_bucket is not configured, skipping data source lookup")
            return knowledge_base_id, data_source_id

        response = client.list_data_sources(
            knowledgeBaseId=knowledge_base_id,
            maxResults=10
        )        
        logger.info(f"(list_data_sources) response: {response}")
        
        data_source_name = sanitize_data_source_name(s3_bucket)
        summaries = response.get("dataSourceSummaries") or []
        for data_source in summaries:
            logger.info(f"data_source: {data_source}")
            if data_source.get("name") == data_source_name:
                data_source_id = data_source["dataSourceId"]
                logger.info(f"data_source_id: {data_source_id}")
                break
        # Fall back to the first AVAILABLE (or first) data source when names diverge.
        if not data_source_id and summaries:
            preferred = next(
                (
                    ds
                    for ds in summaries
                    if (ds.get("status") or "").upper() == "AVAILABLE"
                ),
                summaries[0],
            )
            data_source_id = preferred.get("dataSourceId")
            logger.warning(
                "data source name mismatch (wanted=%s); using %s (%s)",
                data_source_name,
                preferred.get("name"),
                data_source_id,
            )

        if knowledge_base_id and data_source_id:
            config["knowledge_base_id"] = knowledge_base_id
            config["data_source_id"] = data_source_id
            config["s3_bucket"] = s3_bucket
            config["region"] = region
            config["projectName"] = projectName
            config["accountId"] = accountId
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
                f.write("\n")

    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")

    return knowledge_base_id, data_source_id

if not knowledge_base_id or not data_source_id:
    knowledge_base_id, data_source_id = update_rag_info()

ACTIVE_INGESTION_STATUSES = ("STARTING", "IN_PROGRESS")


def refresh_rag_ids() -> bool:
    """Refresh in-memory KB/data-source IDs from AWS and persist to config.json."""
    global knowledge_base_id, data_source_id
    kb_id, ds_id = update_rag_info()
    if kb_id and ds_id:
        knowledge_base_id = kb_id
        data_source_id = ds_id
        logger.info(
            "Refreshed RAG ids: knowledge_base_id=%s data_source_id=%s",
            knowledge_base_id,
            data_source_id,
        )
        return True
    logger.error(
        "Failed to refresh RAG ids (knowledge_base_id=%s data_source_id=%s)",
        kb_id,
        ds_id,
    )
    return False


def _is_resource_not_found(exc: Exception) -> bool:
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException"
    return "ResourceNotFoundException" in type(exc).__name__


def get_active_ingestion_job(*, _retried: bool = False) -> dict | None:
    """Return an in-flight ingestion job if Knowledge Base sync is already running."""
    if not knowledge_base_id or not data_source_id:
        logger.error("knowledge_base_id or data_source_id is not configured")
        if not _retried and refresh_rag_ids():
            return get_active_ingestion_job(_retried=True)
        return None

    try:
        bedrock_client = boto3.client(
            service_name="bedrock-agent",
            region_name=region,
        )
        for status in ACTIVE_INGESTION_STATUSES:
            response = bedrock_client.list_ingestion_jobs(
                knowledgeBaseId=knowledge_base_id,
                dataSourceId=data_source_id,
                filters=[
                    {
                        "attribute": "STATUS",
                        "operator": "EQ",
                        "values": [status],
                    }
                ],
                maxResults=1,
                sortBy={
                    "attribute": "STARTED_AT",
                    "order": "DESCENDING",
                },
            )
            summaries = response.get("ingestionJobSummaries") or []
            if not summaries:
                continue
            job = summaries[0]
            logger.info("Active ingestion job found: %s", job)
            return {
                "ingestion_job_id": job.get("ingestionJobId"),
                "status": job.get("status"),
                "started_at": str(job["startedAt"]) if job.get("startedAt") else None,
            }
        return None
    except Exception as e:
        if not _retried and _is_resource_not_found(e):
            logger.warning(
                "Stale knowledge_base_id/data_source_id (%s / %s); refreshing",
                knowledge_base_id,
                data_source_id,
            )
            if refresh_rag_ids():
                return get_active_ingestion_job(_retried=True)
        logger.error("Error listing ingestion jobs: %s", traceback.format_exc())
        raise


def sync_data_source(*, _retried: bool = False):
    """Start a Knowledge Base ingestion job for the configured data source."""
    if not knowledge_base_id or not data_source_id:
        logger.error("knowledge_base_id or data_source_id is not configured")
        if not _retried and refresh_rag_ids():
            return sync_data_source(_retried=True)
        return None

    try:
        bedrock_client = boto3.client(
            service_name="bedrock-agent",
            region_name=region,
        )
        response = bedrock_client.start_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
        )
        logger.info("(start_ingestion_job) response: %s", response)
        job = response.get("ingestionJob", {})
        return {
            "ingestion_job_id": job.get("ingestionJobId"),
            "status": job.get("status"),
        }
    except Exception as e:
        if not _retried and _is_resource_not_found(e):
            logger.warning(
                "Stale knowledge_base_id/data_source_id (%s / %s); refreshing",
                knowledge_base_id,
                data_source_id,
            )
            if refresh_rag_ids():
                return sync_data_source(_retried=True)
        logger.error("Error syncing data source: %s", traceback.format_exc())
        return None


def _sanitize_s3_user_segment(user_id: str | None) -> str | None:
    """Return a safe single path segment for per-user S3 folders, or None."""
    return sanitize_user_path_segment(user_id)


def docs_s3_prefix(project: str | None = None) -> str:
    """Return S3 key prefix for RAG docs: ``docs/{projectName}``."""
    name = (project or projectName or "").strip().strip("/")
    if not name:
        name = "default"
    return f"docs/{name}"


def upload_to_s3(
    file_bytes: bytes,
    file_name: str,
    user_id: str | None = None,
) -> dict | None:
    """Upload a file to S3 under docs/{projectName}/ (or images/) and return metadata.

    When ``user_id`` is provided, the object key becomes
    ``docs/{projectName}/{user_id}/{file_name}`` so each user has a separate folder.
    """
    if not s3_bucket:
        logger.error("s3_bucket is not configured")
        return None

    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        content_type = get_contents_type(file_name)
        logger.info("content_type: %s", content_type)

        prefix = (
            "images"
            if isinstance(content_type, str) and content_type.startswith("image/")
            else docs_s3_prefix()
        )
        user_segment = _sanitize_s3_user_segment(user_id)
        if user_segment:
            s3_key = f"{prefix}/{user_segment}/{file_name}"
            relative_url_path = f"{prefix}/{parse.quote(user_segment)}/{parse.quote(file_name)}"
        else:
            s3_key = f"{prefix}/{file_name}"
            relative_url_path = f"{prefix}/{parse.quote(file_name)}"
        user_meta = {"content_type": content_type}

        put_params = {
            "Bucket": s3_bucket,
            "Key": s3_key,
            "Metadata": user_meta,
            "Body": file_bytes,
            "CacheControl": "no-cache, max-age=0, must-revalidate",
        }
        if content_type and content_type != "no info":
            put_params["ContentType"] = content_type
        if content_type == "application/pdf":
            put_params["ContentDisposition"] = "inline"

        response = s3_client.put_object(**put_params)
        logger.info("upload response: %s", response)

        url = None
        if sharing_url:
            url = f"{sharing_url.rstrip('/')}/{relative_url_path}"

        return {
            "file_name": file_name,
            "s3_key": s3_key,
            "content_type": content_type,
            "url": url,
        }
    except Exception:
        logger.error("Error uploading to S3: %s", traceback.format_exc())
        return None


def rag_docs_s3_key(file_name: str, user_id: str | None = None) -> str:
    """Build ``docs/{project}/{user}/{file}`` key used by Knowledge Base ingest."""
    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    prefix = docs_s3_prefix()
    user_segment = _sanitize_s3_user_segment(user_id)
    if user_segment:
        return f"{prefix}/{user_segment}/{safe_name}"
    return f"{prefix}/{safe_name}"


def rag_docs_public_url(file_name: str, user_id: str | None = None) -> str | None:
    """CloudFront/sharing URL for a docs/{project}/ object, if configured."""
    if not sharing_url:
        return None
    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    prefix = docs_s3_prefix()
    user_segment = _sanitize_s3_user_segment(user_id)
    if user_segment:
        relative = f"{prefix}/{parse.quote(user_segment)}/{parse.quote(safe_name)}"
    else:
        relative = f"{prefix}/{parse.quote(safe_name)}"
    return f"{sharing_url.rstrip('/')}/{relative}"


def s3_uri_to_sharing_url(uri: str, sharing_base: str | None = None) -> str | None:
    """Map ``s3://bucket/key`` to ``{sharing_base}/key`` using the full object key.

    RAG citations must keep ``docs/{project}/{user}/file.pdf`` — using only
    ``docs/{filename}`` yields CloudFront AccessDenied (object missing).
    """
    base = (sharing_base if sharing_base is not None else sharing_url) or ""
    base = base.strip().rstrip("/")
    if not uri or not uri.startswith("s3://") or not base:
        return None
    rest = uri[5:]
    parts = rest.split("/", 1)
    if len(parts) < 2 or not parts[1]:
        return None
    encoded = "/".join(parse.quote(seg) for seg in parts[1].split("/"))
    return f"{base}/{encoded}"


def _s3_client_for_presign():
    """S3 client for browser-safe regional, virtual-hosted presigned URLs.

    Global ``*.s3.amazonaws.com`` hosts often 307-redirect to the region
    endpoint; browsers then fail the signed PUT (403/CORS). Prefer
    virtual-hosted ``https://{bucket}.s3.{region}.amazonaws.com/...``.
    """
    from botocore.config import Config

    region = bedrock_region or "us-west-2"
    return boto3.client(
        service_name="s3",
        region_name=region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "virtual"},
        ),
    )


def generate_rag_upload_presigned_put(
    file_name: str,
    user_id: str | None = None,
    *,
    expires_in: int = 900,
) -> dict | None:
    """Return a browser-usable presigned PUT URL for RAG docs uploads.

    Only ``Content-Type`` is signed (same as Load-files) so browser PUT
    matches CORS/signature. Keys use :func:`docs_s3_prefix`.
    """
    if not s3_bucket:
        logger.error("s3_bucket is not configured")
        return None

    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    s3_key = rag_docs_s3_key(safe_name, user_id=user_id)
    content_type = _session_upload_content_type(safe_name)
    headers = {"Content-Type": content_type}
    params: dict = {
        "Bucket": s3_bucket,
        "Key": s3_key,
        "ContentType": content_type,
    }

    try:
        s3_client = _s3_client_for_presign()
        upload_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=max(60, int(expires_in)),
            HttpMethod="PUT",
        )
        logger.info(
            "rag upload presign key=%s host=%s",
            s3_key,
            parse.urlparse(upload_url).netloc,
        )
        return {
            "file_name": safe_name,
            "s3_key": s3_key,
            "content_type": content_type,
            "upload_url": upload_url,
            "headers": headers,
            "expires_in": max(60, int(expires_in)),
            "url": rag_docs_public_url(safe_name, user_id=user_id),
        }
    except Exception:
        logger.error(
            "Error generating rag upload presign: %s", traceback.format_exc()
        )
        return None


# Staging prefix for browser → S3 Load-files PUTs (then mirrored to SESSION_STORAGE).
SESSION_UPLOAD_S3_PREFIX = "session-uploads"


def session_upload_s3_key(file_name: str, user_id: str | None = None) -> str:
    """Build ``session-uploads/{user}/upload/{file}`` object key."""
    segment = sanitize_user_path_segment(user_id) or "default"
    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    return f"{SESSION_UPLOAD_S3_PREFIX}/{segment}/upload/{safe_name}"


def _session_upload_content_type(file_name: str) -> str:
    """Content-Type for session uploads; never returns ``no info``."""
    content_type = get_contents_type(file_name)
    if not content_type or content_type == "no info":
        return "application/octet-stream"
    return content_type


def local_session_upload_path(file_name: str, user_id: str | None = None) -> str:
    """Absolute path: ``SESSION_STORAGE_DIR/{user}/upload/{file}``."""
    segment = sanitize_user_path_segment(user_id) or "default"
    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    return os.path.join(SESSION_STORAGE_DIR, segment, "upload", safe_name)


def upload_to_session_upload(
    file_bytes: bytes,
    file_name: str,
    user_id: str | None = None,
) -> dict | None:
    """Save a Load-files attachment under SESSION_STORAGE_DIR/{user}/upload/.

    Returns metadata including the absolute local path as ``path``.
    """
    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    dest_path = local_session_upload_path(safe_name, user_id=user_id)
    content_type = _session_upload_content_type(safe_name)

    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(file_bytes)
        logger.info(
            "session upload saved user=%s path=%s bytes=%s",
            sanitize_user_path_segment(user_id) or "default",
            dest_path,
            len(file_bytes),
        )
        return {
            "file_name": safe_name,
            "s3_key": dest_path,
            "path": dest_path,
            "content_type": content_type,
        }
    except Exception:
        logger.error("Error saving session upload: %s", traceback.format_exc())
        return None


def generate_session_upload_presigned_put(
    file_name: str,
    user_id: str | None = None,
    *,
    expires_in: int = 900,
) -> dict | None:
    """Return a browser-usable presigned PUT URL for Load-files uploads.

    The client must PUT the raw body with the returned ``headers`` (especially
    ``Content-Type``) so the signature matches. Call
    :func:`materialize_session_upload_from_s3` after the PUT so the agent can
    read the file from local SESSION_STORAGE.
    """
    if not s3_bucket:
        logger.error("s3_bucket is not configured")
        return None

    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    s3_key = session_upload_s3_key(safe_name, user_id=user_id)
    content_type = _session_upload_content_type(safe_name)
    headers = {"Content-Type": content_type}
    params: dict = {
        "Bucket": s3_bucket,
        "Key": s3_key,
        "ContentType": content_type,
    }
    if content_type == "application/pdf":
        params["ContentDisposition"] = "inline"
        headers["Content-Disposition"] = "inline"

    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        upload_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=max(60, int(expires_in)),
            HttpMethod="PUT",
        )
        return {
            "file_name": safe_name,
            "s3_key": s3_key,
            "content_type": content_type,
            "upload_url": upload_url,
            "headers": headers,
            "expires_in": max(60, int(expires_in)),
        }
    except Exception:
        logger.error(
            "Error generating session upload presign: %s", traceback.format_exc()
        )
        return None


def head_session_upload_object(s3_key: str) -> dict | None:
    """HEAD an object; return ``{content_length, content_type}`` or None."""
    if not s3_bucket or not s3_key:
        return None
    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        response = s3_client.head_object(Bucket=s3_bucket, Key=s3_key)
        return {
            "content_length": int(response.get("ContentLength") or 0),
            "content_type": response.get("ContentType"),
        }
    except Exception:
        logger.error("Error head_object key=%s: %s", s3_key, traceback.format_exc())
        return None


def materialize_session_upload_from_s3(
    s3_key: str,
    file_name: str,
    user_id: str | None = None,
) -> dict | None:
    """Download a staged S3 Load-files object into SESSION_STORAGE_DIR."""
    if not s3_bucket or not s3_key:
        return None
    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    dest_path = local_session_upload_path(safe_name, user_id=user_id)
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        s3_client.download_file(s3_bucket, s3_key, dest_path)
        size = os.path.getsize(dest_path) if os.path.isfile(dest_path) else 0
        content_type = _session_upload_content_type(safe_name)
        logger.info(
            "session upload materialized user=%s s3_key=%s path=%s bytes=%s",
            sanitize_user_path_segment(user_id) or "default",
            s3_key,
            dest_path,
            size,
        )
        return {
            "file_name": safe_name,
            "s3_key": s3_key,
            "path": dest_path,
            "content_type": content_type,
            "content_length": size,
        }
    except Exception:
        logger.error(
            "Error materializing session upload key=%s: %s",
            s3_key,
            traceback.format_exc(),
        )
        return None


# ---------------------------------------------------------------------------
# ESS docs uploads (browser → S3 presigned PUT → materialize into ess/regulations/)
# ---------------------------------------------------------------------------

ESS_DOCS_S3_PREFIX = "session-uploads"
MAX_ESS_DOC_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def ess_docs_s3_key(file_name: str, user_id: str | None = None) -> str:
    """Build ``session-uploads/{user}/ess/{file}`` staging key."""
    segment = sanitize_user_path_segment(user_id) or "default"
    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    return f"{ESS_DOCS_S3_PREFIX}/{segment}/ess/{safe_name}"


def generate_ess_docs_presigned_put(
    file_name: str,
    user_id: str | None = None,
    *,
    expires_in: int = 900,
) -> dict | None:
    """Return a browser-usable presigned PUT URL for ESS docs uploads."""
    if not s3_bucket:
        logger.error("s3_bucket is not configured")
        return None

    original = os.path.basename(file_name or "").strip() or "upload.bin"
    try:
        _ensure_ess_on_path()
        from doc_list import sanitize_ess_filename

        safe_name = sanitize_ess_filename(original)
    except Exception:
        safe_name = original.replace(" ", "_")

    s3_key = ess_docs_s3_key(safe_name, user_id=user_id)
    content_type = _session_upload_content_type(safe_name)
    headers = {"Content-Type": content_type}
    params: dict = {
        "Bucket": s3_bucket,
        "Key": s3_key,
        "ContentType": content_type,
    }
    if content_type == "application/pdf":
        params["ContentDisposition"] = "inline"
        headers["Content-Disposition"] = "inline"

    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        upload_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=max(60, int(expires_in)),
            HttpMethod="PUT",
        )
        return {
            "file_name": safe_name,
            "original_filename": original,
            "sanitized": original != safe_name,
            "s3_key": s3_key,
            "content_type": content_type,
            "upload_url": upload_url,
            "headers": headers,
            "expires_in": max(60, int(expires_in)),
        }
    except Exception:
        logger.error(
            "Error generating ESS docs presign: %s", traceback.format_exc()
        )
        return None


def materialize_ess_docs_from_s3(
    s3_key: str,
    file_name: str,
    user_id: str | None = None,
    *,
    original_filename: str | None = None,
) -> dict | None:
    """Download a staged ESS object into ``{user}/ess/regulations/`` and update regulations_list."""
    if not s3_bucket or not s3_key:
        return None

    original = (
        os.path.basename(original_filename or file_name or "").strip()
        or "upload.bin"
    )
    try:
        _ensure_ess_on_path()
        from doc_list import sanitize_ess_filename, upsert_document

        safe_name = sanitize_ess_filename(file_name or original)
    except Exception:
        safe_name = os.path.basename(file_name or original) or "upload.bin"
        upsert_document = None  # type: ignore[assignment]

    ess = ensure_user_ess_dir(user_id)
    docs = os.path.join(ess, "regulations")
    os.makedirs(docs, exist_ok=True)
    dest_path = os.path.join(docs, safe_name)
    overwritten = os.path.isfile(dest_path)

    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        s3_client.download_file(s3_bucket, s3_key, dest_path)
        size = os.path.getsize(dest_path) if os.path.isfile(dest_path) else 0
        if size <= 0:
            logger.error("ESS materialize produced empty file: %s", dest_path)
            return None

        segment = sanitize_user_path_segment(user_id) or "default"
        if upsert_document is not None:
            try:
                upsert_document(
                    ess,
                    filename=safe_name,
                    source_path=os.path.abspath(dest_path),
                    bytes_size=size,
                    status="uploaded",
                    user_id=segment,
                    extra={
                        "original_filename": original,
                        "sanitized": original != safe_name,
                        "s3_key": s3_key,
                    },
                )
            except Exception:
                logger.exception("Failed to update ess doc_list after materialize")

        logger.info(
            "ess docs materialized user=%s s3_key=%s path=%s bytes=%s",
            segment,
            s3_key,
            dest_path,
            size,
        )
        return {
            "ess_dir": ess,
            "docs_dir": docs,
            "raw_dir": docs,
            "saved": {
                "name": safe_name,
                "original_filename": original,
                "sanitized": original != safe_name,
                "path": dest_path,
                "bytes": size,
                "overwritten": overwritten,
            },
            "count": 1,
            "s3_key": s3_key,
            "doc_list": ess_doc_list_path(user_id),
            "content_type": _session_upload_content_type(safe_name),
            "content_length": size,
        }
    except Exception:
        logger.error(
            "Error materializing ESS docs key=%s: %s",
            s3_key,
            traceback.format_exc(),
        )
        return None


def ess_projects_s3_key(file_name: str, user_id: str | None = None) -> str:
    """Build ``session-uploads/{user}/ess/projects/{file}`` staging key."""
    segment = sanitize_user_path_segment(user_id) or "default"
    safe_name = os.path.basename(file_name or "").strip() or "upload.bin"
    return f"{ESS_DOCS_S3_PREFIX}/{segment}/ess/projects/{safe_name}"


def generate_ess_projects_presigned_put(
    file_name: str,
    user_id: str | None = None,
    *,
    expires_in: int = 900,
) -> dict | None:
    """Return a browser-usable presigned PUT URL for ESS project docs uploads."""
    if not s3_bucket:
        logger.error("s3_bucket is not configured")
        return None

    original = os.path.basename(file_name or "").strip() or "upload.bin"
    try:
        _ensure_ess_on_path()
        from doc_list import sanitize_ess_filename

        safe_name = sanitize_ess_filename(original)
    except Exception:
        safe_name = original.replace(" ", "_")

    s3_key = ess_projects_s3_key(safe_name, user_id=user_id)
    content_type = _session_upload_content_type(safe_name)
    headers = {"Content-Type": content_type}
    params: dict = {
        "Bucket": s3_bucket,
        "Key": s3_key,
        "ContentType": content_type,
    }
    if content_type == "application/pdf":
        params["ContentDisposition"] = "inline"
        headers["Content-Disposition"] = "inline"

    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        upload_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=max(60, int(expires_in)),
            HttpMethod="PUT",
        )
        return {
            "file_name": safe_name,
            "original_filename": original,
            "sanitized": original != safe_name,
            "s3_key": s3_key,
            "content_type": content_type,
            "upload_url": upload_url,
            "headers": headers,
            "expires_in": max(60, int(expires_in)),
        }
    except Exception:
        logger.error(
            "Error generating ESS projects presign: %s", traceback.format_exc()
        )
        return None


def materialize_ess_projects_from_s3(
    s3_key: str,
    file_name: str,
    user_id: str | None = None,
    *,
    original_filename: str | None = None,
) -> dict | None:
    """Download a staged ESS object into ``{user}/ess/projects/`` and update project_list."""
    if not s3_bucket or not s3_key:
        return None

    original = (
        os.path.basename(original_filename or file_name or "").strip()
        or "upload.bin"
    )
    try:
        _ensure_ess_on_path()
        from doc_list import PROJECTS, sanitize_ess_filename, upsert_document

        safe_name = sanitize_ess_filename(file_name or original)
    except Exception:
        safe_name = os.path.basename(file_name or original) or "upload.bin"
        upsert_document = None  # type: ignore[assignment]
        PROJECTS = None  # type: ignore[assignment]

    ess = ensure_user_ess_dir(user_id)
    projects = os.path.join(ess, "projects")
    os.makedirs(projects, exist_ok=True)
    dest_path = os.path.join(projects, safe_name)
    overwritten = os.path.isfile(dest_path)

    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        s3_client.download_file(s3_bucket, s3_key, dest_path)
        size = os.path.getsize(dest_path) if os.path.isfile(dest_path) else 0
        if size <= 0:
            logger.error("ESS project materialize produced empty file: %s", dest_path)
            return None

        segment = sanitize_user_path_segment(user_id) or "default"
        if upsert_document is not None and PROJECTS is not None:
            try:
                upsert_document(
                    ess,
                    filename=safe_name,
                    source_path=os.path.abspath(dest_path),
                    bytes_size=size,
                    status="uploaded",
                    user_id=segment,
                    extra={
                        "original_filename": original,
                        "sanitized": original != safe_name,
                        "s3_key": s3_key,
                    },
                    registry=PROJECTS,
                )
            except Exception:
                logger.exception("Failed to update ess project_list after materialize")

        logger.info(
            "ess projects materialized user=%s s3_key=%s path=%s bytes=%s",
            segment,
            s3_key,
            dest_path,
            size,
        )
        return {
            "ess_dir": ess,
            "projects_dir": projects,
            "docs_dir": projects,
            "raw_dir": projects,
            "saved": {
                "name": safe_name,
                "original_filename": original,
                "sanitized": original != safe_name,
                "path": dest_path,
                "bytes": size,
                "overwritten": overwritten,
            },
            "count": 1,
            "s3_key": s3_key,
            "doc_list": ess_project_list_path(user_id),
            "project_list": ess_project_list_path(user_id),
            "content_type": _session_upload_content_type(safe_name),
            "content_length": size,
        }
    except Exception:
        logger.error(
            "Error materializing ESS projects key=%s: %s",
            s3_key,
            traceback.format_exc(),
        )
        return None


# ---------------------------------------------------------------------------
# ESS document list — CloudFront URLs (PDF) + artifacts MD publish
# ---------------------------------------------------------------------------

def ess_pdf_s3_key(file_name: str, user_id: str | None = None) -> str:
    """S3 key for an ESS PDF uploaded via Configure (session-uploads staging)."""
    return ess_docs_s3_key(file_name, user_id=user_id)


def ess_project_pdf_public_url(
    file_name: str, user_id: str | None = None
) -> str | None:
    """CloudFront URL for ``session-uploads/{user}/ess/projects/{pdf}``."""
    if not sharing_url:
        return None
    safe_name = os.path.basename(file_name or "").strip()
    if not safe_name:
        return None
    segment = sanitize_user_path_segment(user_id) or "default"
    relative = (
        f"{ESS_DOCS_S3_PREFIX}/{parse.quote(segment)}/ess/projects/"
        f"{parse.quote(safe_name)}"
    )
    return f"{sharing_url.rstrip('/')}/{relative}"


def ess_pdf_public_url(file_name: str, user_id: str | None = None) -> str | None:
    """CloudFront URL for ``session-uploads/{user}/ess/{pdf}`` when sharing_url is set."""
    if not sharing_url:
        return None
    safe_name = os.path.basename(file_name or "").strip()
    if not safe_name:
        return None
    segment = sanitize_user_path_segment(user_id) or "default"
    relative = (
        f"{ESS_DOCS_S3_PREFIX}/{parse.quote(segment)}/ess/{parse.quote(safe_name)}"
    )
    return f"{sharing_url.rstrip('/')}/{relative}"


def ess_md_artifacts_s3_key(file_name: str, user_id: str | None = None) -> str:
    """``artifacts/{projectName}/{user}/md/{stem}.md`` for CloudFront viewing."""
    segment = sanitize_user_path_segment(user_id) or "default"
    safe_name = os.path.basename(file_name or "").strip() or "document.md"
    if not safe_name.lower().endswith(".md"):
        safe_name = f"{os.path.splitext(safe_name)[0]}.md"
    project = (projectName or "default").strip().strip("/") or "default"
    return f"artifacts/{project}/{segment}/md/{safe_name}"


def ess_md_artifacts_public_url(
    file_name: str, user_id: str | None = None
) -> str | None:
    if not sharing_url:
        return None
    key = ess_md_artifacts_s3_key(file_name, user_id=user_id)
    # Quote each path segment; keep slashes.
    parts = [parse.quote(p) for p in key.split("/")]
    return f"{sharing_url.rstrip('/')}/{'/'.join(parts)}"


def ess_md_local_artifacts_path(
    file_name: str, user_id: str | None = None
) -> str:
    """Local mirror: ``{user}/artifacts/md/{stem}.md``."""
    artifacts = ensure_user_artifacts_dir(user_id)
    md_dir = os.path.join(artifacts, "md")
    os.makedirs(md_dir, exist_ok=True)
    safe_name = os.path.basename(file_name or "").strip() or "document.md"
    if not safe_name.lower().endswith(".md"):
        safe_name = f"{os.path.splitext(safe_name)[0]}.md"
    return os.path.join(md_dir, safe_name)


def publish_ess_markdown_to_artifacts(
    md_path: str,
    user_id: str | None = None,
    *,
    file_name: str | None = None,
) -> dict | None:
    """Copy markdown next to artifacts and upload to S3 for CloudFront.

    Target key: ``artifacts/{projectName}/{user_id}/md/{name}.md``.
    """
    from pathlib import Path

    src = Path(md_path)
    if not src.is_file():
        logger.warning("ESS md publish skipped; missing file: %s", src)
        return None

    name = os.path.basename(file_name or src.name)
    if not name.lower().endswith(".md"):
        name = f"{os.path.splitext(name)[0]}.md"

    local_dest = ess_md_local_artifacts_path(name, user_id=user_id)
    try:
        src_stat = src.stat()
        if (
            os.path.isfile(local_dest)
            and os.path.getsize(local_dest) == src_stat.st_size
            and os.path.getmtime(local_dest) >= src_stat.st_mtime
            and s3_bucket
        ):
            # Local mirror already fresh — still ensure S3 object exists.
            s3_key = ess_md_artifacts_s3_key(name, user_id=user_id)
            public_url = ess_md_artifacts_public_url(name, user_id=user_id)
            head = _head_s3_object_quiet(s3_key)
            if head and int(head.get("content_length") or 0) == src_stat.st_size:
                return {
                    "file_name": name,
                    "local_path": local_dest,
                    "s3_key": s3_key,
                    "url": public_url,
                    "uploaded": True,
                    "skipped": True,
                    "bytes": src_stat.st_size,
                }
        if os.path.abspath(str(src)) != os.path.abspath(local_dest):
            import shutil

            shutil.copy2(src, local_dest)
    except Exception:
        logger.exception("Failed to copy ESS md to local artifacts: %s", src)
        local_dest = str(src.resolve())

    s3_key = ess_md_artifacts_s3_key(name, user_id=user_id)
    public_url = ess_md_artifacts_public_url(name, user_id=user_id)
    result = {
        "file_name": name,
        "local_path": local_dest,
        "s3_key": s3_key,
        "url": public_url,
        "uploaded": False,
    }

    if not s3_bucket:
        logger.warning("s3_bucket not configured; ESS md kept local only")
        return result

    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        content_type = get_contents_type(name)
        if content_type == "no info":
            content_type = "text/markdown; charset=utf-8"
        with open(local_dest, "rb") as f:
            body = f.read()
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=s3_key,
            Body=body,
            ContentType=content_type,
            CacheControl="no-cache, max-age=0, must-revalidate",
        )
        result["uploaded"] = True
        result["bytes"] = len(body)
        logger.info(
            "ESS md published user=%s s3_key=%s bytes=%s url=%s",
            sanitize_user_path_segment(user_id) or "default",
            s3_key,
            len(body),
            public_url,
        )
        return result
    except Exception:
        logger.error(
            "Error publishing ESS md to artifacts: %s", traceback.format_exc()
        )
        return result


def head_ess_pdf_on_s3(
    file_name: str,
    user_id: str | None = None,
    *,
    kind: str = "regulation",
) -> bool:
    """True when the ESS PDF object exists under session-uploads (CloudFront-ready)."""
    if kind == "project":
        key = ess_projects_s3_key(file_name, user_id=user_id)
    else:
        key = ess_pdf_s3_key(file_name, user_id=user_id)
    if not s3_bucket or not key:
        return False
    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        s3_client.head_object(Bucket=s3_bucket, Key=key)
        return True
    except Exception:
        return False


def _head_s3_object_quiet(s3_key: str) -> dict | None:
    if not s3_bucket or not s3_key:
        return None
    try:
        s3_client = boto3.client(service_name="s3", region_name=bedrock_region)
        response = s3_client.head_object(Bucket=s3_bucket, Key=s3_key)
        return {
            "content_length": int(response.get("ContentLength") or 0),
            "content_type": response.get("ContentType"),
        }
    except Exception:
        return None


def enrich_ess_documents_for_ui(
    documents: list[dict],
    user_id: str | None = None,
    *,
    publish_md: bool = True,
    kind: str = "regulation",
) -> list[dict]:
    """Attach pdf/md view URLs for Regulations / Projects UI.

    PDF: prefer CloudFront session-uploads; else API fallback.
    MD: copy+upload to ``artifacts/{project}/{user}/md/`` then expose CloudFront + viewer URL.
    """
    is_project = kind == "project"
    docs_root = ess_projects_dir(user_id) if is_project else ess_docs_dir(user_id)
    kind_qs = "?kind=project" if is_project else ""

    enriched: list[dict] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        item = dict(doc)
        filename = str(item.get("filename") or "").strip()
        md_file = str(item.get("md_file") or item.get("md_path") or "").strip()
        md_name = os.path.basename(md_file) if md_file else ""
        if not md_name and filename:
            stem = os.path.splitext(filename)[0]
            md_name = f"{stem}.md"

        pdf_name = filename if filename.lower().endswith(".pdf") else ""
        if not pdf_name and filename:
            # source may be pdf even if filename field uses another form
            src = str(item.get("source_path") or "")
            if src.lower().endswith(".pdf"):
                pdf_name = os.path.basename(src)

        local_md = str(item.get("md_path") or "").strip()
        if local_md and not os.path.isfile(local_md) and md_name:
            candidate = os.path.join(docs_root, md_name)
            if os.path.isfile(candidate):
                local_md = candidate
        elif not local_md and md_name:
            candidate = os.path.join(docs_root, md_name)
            if os.path.isfile(candidate):
                local_md = candidate

        local_pdf = ""
        if pdf_name:
            candidate = os.path.join(docs_root, pdf_name)
            if os.path.isfile(candidate):
                local_pdf = candidate
            else:
                src = str(item.get("source_path") or "")
                if src and os.path.isfile(src) and src.lower().endswith(".pdf"):
                    local_pdf = src

        if is_project:
            pdf_cf = (
                ess_project_pdf_public_url(pdf_name, user_id=user_id)
                if pdf_name
                else None
            )
        else:
            pdf_cf = (
                ess_pdf_public_url(pdf_name, user_id=user_id) if pdf_name else None
            )
        pdf_on_s3 = bool(
            pdf_name
            and head_ess_pdf_on_s3(pdf_name, user_id=user_id, kind=kind)
        )
        item["pdf_available"] = bool(local_pdf) or pdf_on_s3
        item["pdf_url"] = pdf_cf if pdf_on_s3 else None
        item["pdf_api_url"] = (
            f"/api/ess/documents/{parse.quote(pdf_name)}/pdf{kind_qs}"
            if pdf_name
            else None
        )

        md_url = None
        md_published = False
        if local_md and os.path.isfile(local_md) and publish_md:
            published = publish_ess_markdown_to_artifacts(
                local_md, user_id=user_id, file_name=md_name or None
            )
            if published:
                md_url = published.get("url")
                md_published = bool(published.get("uploaded"))
                item["md_s3_key"] = published.get("s3_key")
                item["md_local_artifacts"] = published.get("local_path")
        elif md_name:
            md_url = ess_md_artifacts_public_url(md_name, user_id=user_id)

        item["md_available"] = bool(local_md and os.path.isfile(local_md))
        item["md_url"] = md_url
        item["md_published"] = md_published
        if local_md and os.path.isfile(local_md):
            try:
                item["md_bytes"] = os.path.getsize(local_md)
            except OSError:
                item["md_bytes"] = None
        else:
            item["md_bytes"] = None
        item["md_viewer_url"] = (
            f"/api/ess/documents/{parse.quote(md_name)}/markdown{kind_qs}"
            if md_name
            else None
        )
        item["display_name"] = (
            str(item.get("original_filename") or "").strip() or filename or md_name
        )
        item["kind"] = kind
        enriched.append(item)
    return enriched


def enrich_ess_test_cases_for_ui(
    documents: list[dict],
    user_id: str | None = None,
) -> list[dict]:
    """Attach xlsx/json view URLs for Test Cases UI."""
    tc_root = ess_test_cases_dir(user_id)
    enriched: list[dict] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        item = dict(doc)
        filename = str(item.get("filename") or "").strip()
        stem = os.path.splitext(filename)[0] if filename else ""

        xlsx_name = filename if filename.lower().endswith(".xlsx") else (
            f"{stem}.xlsx" if stem else ""
        )
        local_xlsx = ""
        if xlsx_name:
            candidate = os.path.join(tc_root, xlsx_name)
            if os.path.isfile(candidate):
                local_xlsx = candidate
            else:
                src = str(item.get("source_path") or "").strip()
                if src and os.path.isfile(src) and src.lower().endswith(".xlsx"):
                    local_xlsx = src
                    xlsx_name = os.path.basename(src)

        json_path = str(item.get("json_path") or "").strip()
        json_name = ""
        local_json = ""
        if json_path and os.path.isfile(json_path):
            local_json = json_path
            json_name = os.path.basename(json_path)
        elif stem:
            candidate = os.path.join(tc_root, f"{stem}.json")
            if os.path.isfile(candidate):
                local_json = candidate
                json_name = f"{stem}.json"

        item["xlsx_available"] = bool(local_xlsx)
        item["xlsx_api_url"] = (
            f"/api/ess/documents/{parse.quote(xlsx_name)}/xlsx"
            if xlsx_name
            else None
        )
        item["json_available"] = bool(local_json)
        item["json_viewer_url"] = (
            f"/api/ess/documents/{parse.quote(json_name or xlsx_name)}/json"
            if (json_name or xlsx_name)
            else None
        )
        if local_xlsx and os.path.isfile(local_xlsx):
            try:
                item["bytes"] = item.get("bytes") or os.path.getsize(local_xlsx)
            except OSError:
                pass
        title = str(item.get("title") or "").strip()
        item["display_name"] = (
            title
            or str(item.get("original_filename") or "").strip()
            or filename
            or json_name
        )
        item["kind"] = "test_case"
        enriched.append(item)
    return enriched
