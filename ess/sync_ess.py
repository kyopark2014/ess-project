#!/usr/bin/env python3
"""ESS sync — PDF/docs → markdown (Wiki Sync staging subset).

Mirrors the document staging path from ``agent-wiki/graph/sync_wiki.py``:
  - classical: pdfplumber / pypdf
  - Foundation Model Parser: PDF → page PNGs (PyMuPDF) → Bedrock Markdown

Working tree (per user)::

    .session_storage/{user}/ess/
      raw/                  uploaded source files
      out/
        converted/          staged .md (+ .pdf_pages for FMP)
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
    root = _session_storage() / _safe_user(user_id) / "ess"
    raw = root / "raw"
    out = root / "out"
    converted = out / "converted"
    for path in (root, raw, out, converted):
        path.mkdir(parents=True, exist_ok=True)
    return root, raw, out, converted


def _fingerprint(raw_dir: Path) -> str:
    parts: list[str] = []
    if not raw_dir.is_dir():
        return hashlib.sha256(b"").hexdigest()
    for path in sorted(raw_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            st = path.stat()
            parts.append(f"{path.name}:{st.st_size}:{int(st.st_mtime)}")
        except OSError:
            continue
    blob = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


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


def _chunk_text(text: str, *, max_chars: int = 10000) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    overlap = 200
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            cut = text.rfind("\n\n", start + max_chars // 2, end)
            if cut > start:
                end = cut
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


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
            f"{len(done)}/{len(page_pngs)} page(s)",
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
    stage: Path, source_path: str, previous_names: list[str]
) -> None:
    """Drop previous markdown chunks for a re-staged source."""
    for name in previous_names:
        path = stage / name
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
    # Also remove any chunk that still points at this source.
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


def _stage_docs_as_markdown(
    files: list[Path],
    stage: Path,
    *,
    use_foundation_model: bool = False,
) -> dict[str, str]:
    """Copy/convert docs into ``stage`` as ``.md`` files.

    Returns mapping of staged markdown absolute path → original source path.
    """
    path_map: dict[str, str] = {}
    used_names: set[str] = {p.name for p in stage.glob("*.md") if p.is_file()}
    pdf_pages_root = stage / ".pdf_pages"
    if use_foundation_model:
        pdf_pages_root.mkdir(parents=True, exist_ok=True)

    def _unique(name: str) -> str:
        if name not in used_names:
            used_names.add(name)
            return name
        stem = Path(name).stem
        suffix = Path(name).suffix
        n = 2
        while True:
            candidate = f"{stem}_{n}{suffix}"
            if candidate not in used_names:
                used_names.add(candidate)
                return candidate
            n += 1

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
        if use_foundation_model and suffix == ".pdf":
            digest = hashlib.sha256(original.encode()).hexdigest()[:8]
            pdf_work = pdf_pages_root / f"{src.stem}_{digest}"
            pdf_work.mkdir(parents=True, exist_ok=True)
            (pdf_work / "source_path.txt").write_text(original + "\n", encoding="utf-8")

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

        if src.suffix.lower() == ".md" and len(body) <= 12000:
            name = _unique(src.name if src.name.endswith(".md") else f"{src.stem}.md")
            dest = stage / name
            dest.write_text(body, encoding="utf-8")
            path_map[str(dest.resolve())] = original
            print(
                f'[ess progress] name="{src.name}" fi={idx} fn={len(files)} pct='
                f"{int(round(100.0 * idx / max(len(files), 1)))} "
                f"| {src.name} · 파일 {idx}/{len(files)} · 완료",
                flush=True,
            )
            continue

        parts = _chunk_text(body, max_chars=10000)
        if not parts:
            print(f"  skip empty after convert: {src.name}", flush=True)
            continue
        print(
            f"  stage {src.name} → {len(parts)} markdown chunk(s) "
            f"({sum(len(p) for p in parts)} chars)",
            flush=True,
        )
        for i, part in enumerate(parts, 1):
            if len(parts) == 1:
                name = _unique(f"{src.stem}.md")
            else:
                name = _unique(f"{src.stem}_part{i:02d}.md")
            dest = stage / name
            header = (
                f"---\nsource_file: \"{original}\"\n"
                f"chunk: {i}\nchunks: {len(parts)}\n---\n\n"
            )
            dest.write_text(header + part, encoding="utf-8")
            path_map[str(dest.resolve())] = original

        print(
            f'[ess progress] name="{src.name}" fi={idx} fn={len(files)} pct='
            f"{int(round(100.0 * idx / max(len(files), 1)))} "
            f"| {src.name} · 파일 {idx}/{len(files)} · 완료",
            flush=True,
        )

    return path_map


def _list_raw_docs(raw_dir: Path) -> list[Path]:
    files = [
        p
        for p in raw_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _DOC_EXTS
    ]
    return sorted(files, key=lambda p: p.name.lower())


def sync_user(user_id: str, *, full: bool = False) -> int:
    ess_root, raw_dir, out_dir, converted = _ess_dirs(user_id)
    settings = _load_settings(user_id)
    use_fmp = bool(settings.get("ess_foundation_model_parser_enabled", True))

    files = _list_raw_docs(raw_dir)
    fp = _fingerprint(raw_dir)
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
        return 0

    if not files and not incomplete:
        print("No files in ess/raw. Nothing to update.")
        fp_path.write_text(fp + "\n", encoding="utf-8")
        return 0

    mode = "foundation-model" if use_fmp else "pdfplumber/pypdf"
    print(f"[ess sync] user={user_id} ess={ess_root}", flush=True)
    print(f"[ess sync] pdf parser: {mode}", flush=True)

    to_stage: list[Path] = []
    if full or not prev:
        print("[ess sync] full convert — refreshing converted/", flush=True)
        _clear_converted(converted, keep_pdf_pages=use_fmp)
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
                    _remove_staged_for_source(converted, key, [str(n) for n in names])
        # Drop converted entries for deleted sources.
        live = {str(p.resolve()) for p in files}
        for key, meta in list(prev_files.items()):
            if key in live:
                continue
            names = meta.get("converted") or []
            if isinstance(names, list):
                _remove_staged_for_source(converted, key, [str(n) for n in names])

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
        f"[ess sync] staging {len(to_stage)} file(s) → {converted}",
        flush=True,
    )
    path_map = _stage_docs_as_markdown(
        to_stage, converted, use_foundation_model=use_fmp
    )
    if not path_map and to_stage:
        print("[ess sync] WARNING: no markdown produced", flush=True)

    # Rebuild file_index for all current raw docs (preserve untouched entries).
    file_index: dict[str, Any] = {}
    staged_by_source: dict[str, list[str]] = {}
    for md_path, source in path_map.items():
        staged_by_source.setdefault(source, []).append(Path(md_path).name)

    for src in files:
        key = str(src.resolve())
        if key in staged_by_source:
            converted_names = staged_by_source[key]
        else:
            old = prev_files.get(key) or {}
            converted_names = list(old.get("converted") or [])
        file_index[key] = {
            "name": src.name,
            "fingerprint": _file_key(src),
            "converted": converted_names,
            "bytes": src.stat().st_size if src.is_file() else 0,
        }

    md_count = len(list(converted.glob("*.md")))
    synced_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "user_id": user_id,
        "synced_at": synced_at,
        "foundation_model_parser_enabled": use_fmp,
        "fingerprint": fp,
        "ess_dir": str(ess_root),
        "converted_dir": str(converted),
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
                "converted_dir": str(converted),
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
        f"in converted/. {fmp_label}.",
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
    args = parser.parse_args()
    try:
        return sync_user(args.user, full=args.full)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1
    except Exception as exc:
        print(f"ESS sync failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
