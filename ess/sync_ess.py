#!/usr/bin/env python3
"""ESS sync — PDF/docs → markdown (Wiki Sync staging subset).

Mirrors the document staging path from ``agent-wiki/graph/sync_wiki.py``:
  - classical: pdfplumber / pypdf
  - Foundation Model Parser: PDF → page PNGs (PyMuPDF) → Bedrock Markdown

Working tree (per user)::

    .session_storage/{user}/ess/
      regulations/          uploaded sources + extracted ``{stem}.md`` / ``{stem}.json``
      regulations_list.json document registry (filename, created_at, md path, …)
      out/
        converted/          FMP intermediates (``.pdf_pages`` only)
        manifest.json
        .last_fingerprint

Usage:
    python ess/sync_ess.py --user alice
    python ess/sync_ess.py --user alice --full
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ESS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _ESS_DIR.parent
_APPLICATION_DIR = _REPO_ROOT / "application"

if str(_ESS_DIR) not in sys.path:
    sys.path.insert(0, str(_ESS_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_APPLICATION_DIR) not in sys.path:
    sys.path.insert(0, str(_APPLICATION_DIR))

_DOC_EXTS = {
    ".pdf",
    ".md",
    ".txt",
    ".text",
    ".rst",
    ".markdown",
}


def _project_root() -> Path:
    return _REPO_ROOT


def _session_storage() -> Path:
    env = os.environ.get("SESSION_STORAGE_DIR")
    if env:
        return Path(env)
    return _APPLICATION_DIR / ".session_storage"


def _safe_user(user_id: str) -> str:
    raw = (user_id or "").strip() or "default"
    return (
        raw.replace("/", "_")
        .replace("\\", "_")
        .replace("..", "_")
    )[:128] or "default"


def _ess_dirs(user_id: str) -> tuple[Path, Path, Path, Path]:
    from doc_list import migrate_raw_to_docs

    root = _session_storage() / _safe_user(user_id) / "ess"
    docs = migrate_raw_to_docs(root)
    out = root / "out"
    converted = out / "converted"
    for path in (root, docs, out, converted):
        path.mkdir(parents=True, exist_ok=True)
    return root, docs, out, converted


def _file_key(path: Path) -> str:
    try:
        st = path.stat()
        return f"{path.name}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return path.name


def _load_settings(user_id: str) -> dict:
    path = _session_storage() / _safe_user(user_id) / "settings.json"
    if not path.is_file():
        return {"ess_foundation_model_parser_enabled": True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ess_foundation_model_parser_enabled": True}
    return data if isinstance(data, dict) else {}


def _load_manifest(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "manifest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _has_non_md_source(docs_dir: Path, stem: str) -> bool:
    """True when ``stem.pdf`` / ``stem.txt`` / … exists (extraction sidecar peer)."""
    for ext in (".pdf", ".txt", ".text", ".rst", ".markdown"):
        if (docs_dir / f"{stem}{ext}").is_file():
            return True
    return False


def _is_extraction_sidecar(path: Path) -> bool:
    """Skip generated ``{stem}.md`` / ``{stem}.json`` sitting next to a source."""
    suf = path.suffix.lower()
    parent = path.parent
    stem = path.stem
    if suf == ".json":
        return _has_non_md_source(parent, stem) or (parent / f"{stem}.md").is_file()
    if suf == ".md":
        return _has_non_md_source(parent, stem)
    return False


def _list_source_docs(docs_dir: Path) -> list[Path]:
    """Source documents to convert (excludes extraction sidecars in ``docs/``)."""
    if not docs_dir.is_dir():
        return []
    files = [
        p
        for p in docs_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in _DOC_EXTS
        and not _is_extraction_sidecar(p)
    ]
    return sorted(files, key=lambda p: p.name.lower())


def _fingerprint(docs_dir: Path) -> str:
    """Fingerprint source docs only (ignore generated ``.md`` / ``.json`` sidecars)."""
    parts: list[str] = []
    for path in _list_source_docs(docs_dir):
        try:
            st = path.stat()
            parts.append(f"{path.name}:{st.st_size}:{int(st.st_mtime)}")
        except OSError:
            continue
    blob = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _collect_image_info(pdf_work: Path | None) -> list[dict[str, Any]]:
    if pdf_work is None:
        return []
    pages_dir = pdf_work / "pages"
    if not pages_dir.is_dir():
        return []
    images: list[dict[str, Any]] = []
    for path in sorted(pages_dir.glob("page_*.png")):
        try:
            st = path.stat()
        except OSError:
            continue
        page_num: int | None = None
        try:
            page_num = int(path.stem.split("_", 1)[1])
        except (IndexError, ValueError):
            page_num = None
        images.append(
            {
                "name": path.name,
                "path": str(path.resolve()),
                "bytes": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                "page": page_num,
            }
        )
    return images


def _source_file_info(src: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": src.name,
        "path": str(src.resolve()),
        "suffix": src.suffix.lower(),
    }
    try:
        st = src.stat()
        info["bytes"] = st.st_size
        info["mtime"] = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        info["bytes"] = 0
        info["mtime"] = None
    return info


def _pdf_to_text(
    path: Path,
    *,
    use_foundation_model: bool = False,
    work_dir: Path | None = None,
) -> str:
    from pdf2text import pdf_to_text

    return pdf_to_text(
        path,
        use_foundation_model=use_foundation_model,
        work_dir=work_dir,
    )


def _doc_to_markdown_body(
    src: Path,
    *,
    use_foundation_model: bool = False,
    pdf_work_dir: Path | None = None,
) -> str | None:
    """Return markdown body for staging, or None if unsupported."""
    suffix = src.suffix.lower()
    if suffix == ".md":
        return src.read_text(encoding="utf-8", errors="replace")
    if suffix in {".txt", ".text", ".rst", ".markdown"}:
        return src.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        body = _pdf_to_text(
            src,
            use_foundation_model=use_foundation_model,
            work_dir=pdf_work_dir,
        ).strip()
        if not body:
            raise ValueError(f"PDF에서 텍스트를 추출하지 못했습니다: {src}")
        return f"# {src.stem}\n\nSource: `{src}`\n\n{body}"
    return None


def _incomplete_foundation_pdfs(
    stage: Path, *, candidates: list[Path] | None = None
) -> list[Path]:
    """PDFs with partial ``.pdf_pages/.../extracted.md`` that should be resumed."""
    from pdf2text import _EXTRACTED_NAME, _pages_done_in_md

    root = stage / ".pdf_pages"
    if not root.is_dir():
        return []

    cand_by_key: dict[str, Path] = {}
    cand_by_name: dict[str, Path] = {}
    for c in candidates or []:
        p = Path(c)
        if not p.is_file() or p.suffix.lower() != ".pdf":
            continue
        try:
            resolved = p.resolve()
        except OSError:
            continue
        digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
        cand_by_key[f"{resolved.stem}_{digest}"] = resolved
        cand_by_name[resolved.name] = resolved

    found: list[Path] = []
    seen: set[str] = set()
    for work in sorted(root.iterdir()):
        if not work.is_dir():
            continue
        marker = work / "source_path.txt"
        src: Path | None = None
        if marker.is_file():
            try:
                line = marker.read_text(encoding="utf-8").strip().splitlines()[0]
                cand = Path(line)
                if cand.is_file():
                    src = cand
            except (OSError, IndexError):
                src = None
        if src is None:
            src = cand_by_key.get(work.name)
            if src is None:
                # Match by stem prefix when path hash changed (sanitize/rename).
                for key, cand in cand_by_key.items():
                    if work.name.startswith(f"{cand.stem}_"):
                        src = cand
                        break
            if src is None:
                # Match by basename from source_path even if file moved.
                if marker.is_file():
                    try:
                        line = marker.read_text(encoding="utf-8").strip().splitlines()[0]
                        src = cand_by_name.get(Path(line).name)
                    except (OSError, IndexError):
                        src = None
            if src is not None:
                try:
                    marker.write_text(str(src.resolve()) + "\n", encoding="utf-8")
                except OSError:
                    pass
        if src is None or not src.is_file():
            continue

        extracted = work / _EXTRACTED_NAME
        pages_dir = work / "pages"
        if not pages_dir.is_dir():
            continue
        page_pngs = sorted(pages_dir.glob("page_*.png"))
        if not page_pngs:
            continue
        done = _pages_done_in_md(extracted)
        if len(done) >= len(page_pngs):
            continue
        key = str(src.resolve())
        if key in seen:
            continue
        seen.add(key)
        found.append(src)
        print(
            f"  [resume] incomplete PDF {src.name}: "
            f"{len(done)}/{len(page_pngs)} page(s) "
            f"(failed/missing will be re-extracted; done pages skip)",
            flush=True,
        )
    return found


def _clear_converted(stage: Path, *, keep_pdf_pages: bool = False) -> None:
    """Refresh converted/ markdown; optionally keep ``.pdf_pages`` for resume."""
    if not stage.exists():
        stage.mkdir(parents=True, exist_ok=True)
        return
    pdf_pages = stage / ".pdf_pages"
    backup: Path | None = None
    if keep_pdf_pages and pdf_pages.is_dir():
        backup = stage.parent / ".pdf_pages_backup"
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        shutil.move(str(pdf_pages), str(backup))
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    if backup is not None and backup.exists():
        shutil.move(str(backup), str(stage / ".pdf_pages"))


def _remove_staged_for_source(
    stage: Path,
    source_path: str,
    previous_names: list[str],
    *,
    src: Path | None = None,
) -> None:
    """Drop previous markdown/json outputs for a re-staged source."""
    parents: list[Path] = [stage]
    if src is not None:
        parents.append(src.parent)
    else:
        try:
            parents.append(Path(source_path).parent)
        except Exception:
            pass

    seen: set[str] = set()
    for name in previous_names:
        for parent in parents:
            path = parent / name
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass

    stem: str | None = None
    if src is not None:
        stem = src.stem
        # Same-folder sidecars next to the source.
        for path in (src.parent / f"{stem}.md", src.parent / f"{stem}.json"):
            if src.suffix.lower() == ".md" and path.resolve() == src.resolve():
                continue
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
    else:
        try:
            stem = Path(source_path).stem
        except Exception:
            stem = None

    # Legacy chunked outputs under converted/
    if stem:
        for path in stage.glob(f"{stem}_part*.md"):
            try:
                path.unlink()
            except OSError:
                pass
        legacy = stage / f"{stem}.md"
        if legacy.is_file():
            try:
                legacy.unlink()
            except OSError:
                pass
        legacy_json = stage / f"{stem}.json"
        if legacy_json.is_file():
            try:
                legacy_json.unlink()
            except OSError:
                pass

    # Also remove any leftover converted chunk that still points at this source.
    for path in stage.glob("*.md"):
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:500]
        except OSError:
            continue
        if f'source_file: "{source_path}"' in head or source_path in head[:200]:
            try:
                path.unlink()
            except OSError:
                pass


def _write_extraction_outputs(
    src: Path,
    body: str,
    *,
    user_id: str,
    use_foundation_model: bool,
    pdf_work: Path | None,
) -> tuple[Path, Path]:
    """Write ``{stem}.md`` + ``{stem}.json`` next to the source file."""
    extracted_at = datetime.now(timezone.utc).isoformat()
    out_dir = src.parent
    md_name = f"{src.stem}.md"
    json_name = f"{src.stem}.json"
    md_path = out_dir / md_name
    json_path = out_dir / json_name

    # Uploaded ``.md`` sources: refresh body in place; never delete the upload.
    header = (
        f"---\nsource_file: \"{str(src.resolve())}\"\n"
        f"extracted_by: \"{user_id}\"\n"
        f"extracted_at: \"{extracted_at}\"\n---\n\n"
    )
    md_path.write_text(header + body.strip() + "\n", encoding="utf-8")

    images = _collect_image_info(pdf_work)
    meta: dict[str, Any] = {
        "filename": md_name,
        "json_filename": json_name,
        "extracted_at": extracted_at,
        "extracted_by": user_id,
        "source": _source_file_info(src),
        "images": images,
        "image_count": len(images),
        "page_count": len(images),
        "char_count": len(body),
        "foundation_model_parser": bool(
            use_foundation_model and src.suffix.lower() == ".pdf"
        ),
        "markdown_path": str(md_path.resolve()),
        "json_path": str(json_path.resolve()),
    }
    if pdf_work is not None:
        meta["pdf_pages_dir"] = str(pdf_work.resolve())
        pages_dir = pdf_work / "pages"
        if pages_dir.is_dir():
            meta["image_dir"] = str(pages_dir.resolve())
        extracted_intermediate = pdf_work / "extracted.md"
        if extracted_intermediate.is_file():
            meta["extracted_intermediate"] = str(extracted_intermediate.resolve())

    json_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return md_path, json_path


def _resolve_pdf_work_dir(
    pdf_pages_root: Path, src: Path, *, create: bool = True
) -> Path:
    """Locate ``.pdf_pages/{stem}_{hash}/`` for *src* (by path hash or source_path.txt)."""
    original = str(src.resolve())
    digest = hashlib.sha256(original.encode()).hexdigest()[:8]
    preferred = pdf_pages_root / f"{src.stem}_{digest}"
    if preferred.is_dir():
        return preferred

    # Fallback: any work dir whose source_path.txt points at this PDF (path rename).
    if pdf_pages_root.is_dir():
        for work in sorted(pdf_pages_root.iterdir()):
            if not work.is_dir():
                continue
            marker = work / "source_path.txt"
            if not marker.is_file():
                continue
            try:
                line = marker.read_text(encoding="utf-8").strip().splitlines()[0]
            except (OSError, IndexError):
                continue
            try:
                if Path(line).resolve() == src.resolve():
                    return work
            except OSError:
                if line == original or Path(line).name == src.name:
                    return work
            # Same stem under docs/ after sanitize/rename of parent folders.
            if Path(line).name == src.name and work.name.startswith(f"{src.stem}_"):
                return work

    if create:
        preferred.mkdir(parents=True, exist_ok=True)
        (preferred / "source_path.txt").write_text(original + "\n", encoding="utf-8")
        return preferred
    return preferred


def _foundation_extraction_complete(pdf_work: Path | None) -> bool:
    """True when ``extracted.md`` has successful text for every page PNG."""
    if pdf_work is None or not pdf_work.is_dir():
        return False
    from pdf2text import _EXTRACTED_NAME, _pages_done_in_md

    pages_dir = pdf_work / "pages"
    extracted = pdf_work / _EXTRACTED_NAME
    if not pages_dir.is_dir() or not extracted.is_file():
        return False
    pngs = sorted(pages_dir.glob("page_*.png"))
    if not pngs:
        return False
    done = _pages_done_in_md(extracted)
    return len(done) >= len(pngs)


def _read_extracted_markdown(pdf_work: Path) -> str:
    from pdf2text import _EXTRACTED_NAME

    return (pdf_work / _EXTRACTED_NAME).read_text(
        encoding="utf-8", errors="replace"
    ).strip()


def _stage_docs_as_markdown(
    files: list[Path],
    stage: Path,
    *,
    user_id: str,
    use_foundation_model: bool = False,
) -> dict[str, str]:
    """Convert docs and write ``{stem}.md`` / ``{stem}.json`` next to each source.

    ``stage`` (``out/converted``) holds FMP ``.pdf_pages`` intermediates only.
    Returns mapping of staged markdown absolute path → original source path.

    When Foundation Model Parser has already extracted every page into
    ``extracted.md`` (same resume rules as agent-wiki ``pdf2text``), LLM calls
    are skipped and existing markdown is reused.
    """
    path_map: dict[str, str] = {}
    pdf_pages_root = stage / ".pdf_pages"
    if use_foundation_model:
        pdf_pages_root.mkdir(parents=True, exist_ok=True)

    for idx, src in enumerate(files, 1):
        suffix = src.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            print(f"  skip image (use PDF for vision staging): {src.name}", flush=True)
            continue

        print(
            f'[ess progress] name="{src.name}" fi={idx} fn={len(files)} '
            f"pct={int(round(100.0 * (idx - 1) / max(len(files), 1)))} "
            f"| {src.name} · 파일 {idx}/{len(files)} · 변환 시작",
            flush=True,
        )

        original = str(src.resolve())
        pdf_work: Path | None = None
        md_out = src.parent / f"{src.stem}.md"
        json_out = src.parent / f"{src.stem}.json"

        if use_foundation_model and suffix == ".pdf":
            pdf_work = _resolve_pdf_work_dir(pdf_pages_root, src, create=True)
            (pdf_work / "source_path.txt").write_text(original + "\n", encoding="utf-8")

            # Already fully extracted → skip LLM (reuse extracted.md / docs md).
            if _foundation_extraction_complete(pdf_work):
                if md_out.is_file() and md_out.stat().st_size > 0:
                    print(
                        f"  skip (already extracted): {src.name} "
                        f"→ {md_out.name}",
                        flush=True,
                    )
                    path_map[str(md_out.resolve())] = original
                    print(
                        f'[ess progress] name="{src.name}" fi={idx} fn={len(files)} pct='
                        f"{int(round(100.0 * idx / max(len(files), 1)))} "
                        f"| {src.name} · 파일 {idx}/{len(files)} · 완료 (skip)",
                        flush=True,
                    )
                    continue
                # Final md missing but intermediates complete — rebuild without LLM.
                body = (
                    f"# {src.stem}\n\nSource: `{src}`\n\n"
                    + _read_extracted_markdown(pdf_work)
                )
                md_path, json_path = _write_extraction_outputs(
                    src,
                    body,
                    user_id=user_id,
                    use_foundation_model=True,
                    pdf_work=pdf_work,
                )
                path_map[str(md_path.resolve())] = original
                print(
                    f"  stage {src.name} → {md_path.name} + {json_path.name} "
                    f"(from extracted.md, no LLM)",
                    flush=True,
                )
                print(
                    f'[ess progress] name="{src.name}" fi={idx} fn={len(files)} pct='
                    f"{int(round(100.0 * idx / max(len(files), 1)))} "
                    f"| {src.name} · 파일 {idx}/{len(files)} · 완료",
                    flush=True,
                )
                continue

        # Non-PDF (or incomplete FMP): if final md already exists and is fresh
        # relative to source, skip re-convert.
        if (
            suffix != ".pdf"
            and md_out.is_file()
            and md_out.stat().st_size > 0
            and json_out.is_file()
        ):
            try:
                if md_out.stat().st_mtime >= src.stat().st_mtime:
                    print(
                        f"  skip (already extracted): {src.name} → {md_out.name}",
                        flush=True,
                    )
                    path_map[str(md_out.resolve())] = original
                    print(
                        f'[ess progress] name="{src.name}" fi={idx} fn={len(files)} pct='
                        f"{int(round(100.0 * idx / max(len(files), 1)))} "
                        f"| {src.name} · 파일 {idx}/{len(files)} · 완료 (skip)",
                        flush=True,
                    )
                    continue
            except OSError:
                pass

        try:
            body = _doc_to_markdown_body(
                src,
                use_foundation_model=use_foundation_model,
                pdf_work_dir=pdf_work,
            )
        except Exception as exc:
            print(f"  WARNING: failed to convert {src.name}: {exc}", flush=True)
            continue
        if body is None:
            print(f"  skip unsupported: {src.name}", flush=True)
            continue
        if not body.strip():
            print(f"  skip empty after convert: {src.name}", flush=True)
            continue

        md_path, json_path = _write_extraction_outputs(
            src,
            body,
            user_id=user_id,
            use_foundation_model=use_foundation_model,
            pdf_work=pdf_work,
        )
        path_map[str(md_path.resolve())] = original
        print(
            f"  stage {src.name} → {md_path.name} + {json_path.name} "
            f"({len(body)} chars)",
            flush=True,
        )
        print(
            f'[ess progress] name="{src.name}" fi={idx} fn={len(files)} pct='
            f"{int(round(100.0 * idx / max(len(files), 1)))} "
            f"| {src.name} · 파일 {idx}/{len(files)} · 완료",
            flush=True,
        )

    return path_map


def sync_user(
    user_id: str,
    *,
    full: bool = False,
    model: str | None = None,
) -> int:
    from doc_list import mark_extracted, remove_document, sync_doc_list_with_filesystem

    model_name = (model or "").strip()
    if model_name:
        os.environ["ESS_VISION_MODEL"] = model_name
        print(f"ESS vision model: {model_name}", flush=True)

    ess_root, docs_dir, out_dir, converted = _ess_dirs(user_id)
    settings = _load_settings(user_id)
    use_fmp = bool(settings.get("ess_foundation_model_parser_enabled", True))

    files = _list_source_docs(docs_dir)
    fp = _fingerprint(docs_dir)
    fp_path = out_dir / ".last_fingerprint"
    prev = fp_path.read_text(encoding="utf-8").strip() if fp_path.is_file() else ""
    prev_manifest = _load_manifest(out_dir)
    prev_files: dict[str, Any] = (
        prev_manifest.get("file_index")
        if isinstance(prev_manifest.get("file_index"), dict)
        else {}
    )

    incomplete: list[Path] = []
    if use_fmp:
        incomplete = _incomplete_foundation_pdfs(converted, candidates=files)

    if not full and fp == prev and prev and not incomplete:
        print("No files changed since last run. Nothing to update.")
        # Keep registry in sync with filesystem even on no-op.
        sync_doc_list_with_filesystem(ess_root, user_id=user_id)
        return 0

    if not files and not incomplete:
        print("No files in ess/regulations. Nothing to update.")
        fp_path.write_text(fp + "\n", encoding="utf-8")
        sync_doc_list_with_filesystem(ess_root, user_id=user_id)
        return 0

    mode = "foundation-model" if use_fmp else "pdfplumber/pypdf"
    print(f"[ess sync] user={user_id} ess={ess_root}", flush=True)
    print(f"[ess sync] pdf parser: {mode}", flush=True)

    to_stage: list[Path] = []
    if full or not prev:
        print("[ess sync] full convert — refreshing intermediates + outputs", flush=True)
        _clear_converted(converted, keep_pdf_pages=use_fmp)
        # Drop legacy chunked markdown left under converted/ and prior docs sidecars.
        for src in files:
            _remove_staged_for_source(
                converted,
                str(src.resolve()),
                [],
                src=src,
            )
        to_stage = list(files)
    else:
        # Incremental: only new/changed + incomplete resumes.
        changed: list[Path] = []
        for src in files:
            key = str(src.resolve())
            meta = prev_files.get(key) or prev_files.get(src.name) or {}
            old_fp = str(meta.get("fingerprint") or "")
            if old_fp != _file_key(src):
                changed.append(src)
                names = meta.get("converted") or []
                if isinstance(names, list):
                    _remove_staged_for_source(
                        converted,
                        key,
                        [str(n) for n in names],
                        src=src,
                    )
        # Drop outputs for deleted sources.
        live = {str(p.resolve()) for p in files}
        for key, meta in list(prev_files.items()):
            if key in live:
                continue
            names = meta.get("converted") or []
            src_hint = Path(key) if key.startswith("/") else None
            if isinstance(names, list):
                _remove_staged_for_source(
                    converted,
                    key,
                    [str(n) for n in names],
                    src=src_hint if src_hint and src_hint.is_file() else None,
                )
            remove_document(ess_root, source_path=key)

        seen = {str(p.resolve()) for p in changed}
        for src in incomplete:
            k = str(src.resolve())
            if k not in seen:
                changed.append(src)
                seen.add(k)
        to_stage = changed
        if not to_stage:
            print("No files changed since last run. Nothing to update.")
            fp_path.write_text(fp + "\n", encoding="utf-8")
            sync_doc_list_with_filesystem(ess_root, user_id=user_id)
            return 0
        print(
            f"[ess sync] incremental: {len(to_stage)} file(s) to convert",
            flush=True,
        )

    if use_fmp:
        print(
            "[ess sync] Foundation Model Parser enabled — PDF→images→LLM",
            flush=True,
        )

    print(
        f"[ess sync] staging {len(to_stage)} file(s) → {docs_dir} "
        f"(intermediates: {converted})",
        flush=True,
    )
    path_map = _stage_docs_as_markdown(
        to_stage,
        converted,
        user_id=user_id,
        use_foundation_model=use_fmp,
    )
    if not path_map and to_stage:
        print("[ess sync] WARNING: no markdown produced", flush=True)

    # Update doc_list for freshly staged markdown.
    for md_path, source in path_map.items():
        md = Path(md_path)
        json_sidecar = md.with_suffix(".json")
        mark_extracted(
            ess_root,
            source_path=source,
            md_path=str(md.resolve()),
            json_path=str(json_sidecar.resolve()) if json_sidecar.is_file() else None,
            user_id=user_id,
        )

    # Rebuild file_index for all current source docs (preserve untouched entries).
    file_index: dict[str, Any] = {}
    staged_by_source: dict[str, list[str]] = {}
    for md_path, source in path_map.items():
        md = Path(md_path)
        names = [md.name, f"{md.stem}.json"]
        staged_by_source.setdefault(source, []).extend(names)

    for src in files:
        key = str(src.resolve())
        if key in staged_by_source:
            converted_names = staged_by_source[key]
        else:
            old = prev_files.get(key) or {}
            converted_names = list(old.get("converted") or [])
            md_sidecar = src.parent / f"{src.stem}.md"
            json_sidecar = src.parent / f"{src.stem}.json"
            current: list[str] = []
            if src.suffix.lower() == ".md":
                current.append(src.name)
            elif md_sidecar.is_file():
                current.append(md_sidecar.name)
            if json_sidecar.is_file():
                current.append(json_sidecar.name)
            if current:
                converted_names = current
        file_index[key] = {
            "name": src.name,
            "fingerprint": _file_key(src),
            "converted": converted_names,
            "bytes": src.stat().st_size if src.is_file() else 0,
            "output_dir": str(src.parent.resolve()),
        }

    md_count = sum(
        1
        for src in files
        if (src.parent / f"{src.stem}.md").is_file()
    )
    synced_at = datetime.now(timezone.utc).isoformat()
    # Final registry rebuild so deleted/renamed files stay consistent.
    doc_list = sync_doc_list_with_filesystem(ess_root, user_id=user_id)

    # Publish extracted markdown to artifacts/{project}/{user}/md/ for CloudFront.
    published_md = 0
    try:
        from application import utils as app_utils

        for doc in doc_list.get("documents") or []:
            if not isinstance(doc, dict):
                continue
            md_path = str(doc.get("md_path") or "").strip()
            md_file = str(doc.get("md_file") or "").strip()
            if not md_path or not Path(md_path).is_file():
                continue
            result = app_utils.publish_ess_markdown_to_artifacts(
                md_path,
                user_id=user_id,
                file_name=md_file or None,
            )
            if result and result.get("uploaded"):
                published_md += 1
        if published_md:
            print(
                f"[ess sync] published {published_md} markdown file(s) → "
                f"artifacts/.../md/ (CloudFront)",
                flush=True,
            )
    except Exception as exc:
        print(f"[ess sync] WARNING: markdown artifacts publish skipped: {exc}", flush=True)

    manifest = {
        "user_id": user_id,
        "synced_at": synced_at,
        "foundation_model_parser_enabled": use_fmp,
        "fingerprint": fp,
        "ess_dir": str(ess_root),
        "docs_dir": str(docs_dir),
        "raw_dir": str(docs_dir),  # backward-compatible
        "converted_dir": str(converted),
        "doc_list": str(ess_root / "regulations_list.json"),
        "doc_count": len(doc_list.get("documents") or []),
        "package": str(_project_root() / "ess"),
        "staged_this_run": len(path_map),
        "markdown_files": md_count,
        "files": [
            {
                "name": p.name,
                "bytes": p.stat().st_size,
                "path": str(p),
            }
            for p in files
        ],
        "file_index": file_index,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fp_path.write_text(fp + "\n", encoding="utf-8")

    package_out = _project_root() / "ess" / "out"
    package_out.mkdir(parents=True, exist_ok=True)
    (package_out / f"last_sync_{_safe_user(user_id)}.json").write_text(
        json.dumps(
            {
                "user_id": user_id,
                "synced_at": synced_at,
                "file_count": len(files),
                "markdown_files": md_count,
                "foundation_model_parser_enabled": use_fmp,
                "session_ess_dir": str(ess_root),
                "docs_dir": str(docs_dir),
                "converted_dir": str(converted),
                "doc_list": str(ess_root / "regulations_list.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    fmp_label = "Foundation Model Parser On" if use_fmp else "Foundation Model Parser Off"
    print(
        f"ESS sync complete: {len(to_stage)} source(s) → {md_count} markdown "
        f"in docs/. {fmp_label}.",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ESS sync (PDF→markdown)")
    parser.add_argument("--user", required=True, help="User id")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force full re-convert of all raw files",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Vision/LLM model name from UI selector (e.g. 'Claude 4.6 Sonnet')",
    )
    args = parser.parse_args()
    try:
        return sync_user(
            args.user,
            full=args.full,
            model=(args.model or "").strip() or None,
        )
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1
    except Exception as exc:
        print(f"ESS sync failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
