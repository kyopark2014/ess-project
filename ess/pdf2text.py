#!/usr/bin/env python3
"""PDF → text for ESS Sync / Wiki Sync semantic staging.

Two backends:
  - classical (default): pdfplumber → pypdf page text
  - foundation model: PDF → per-page PNG (PyMuPDF) → Bedrock multimodal Markdown

Foundation-model vision helpers (``_prepare_image_base64``, ``_extract_text_with_llm``,
``_parse_result``) are built into this module so Sync does not require
``mcp_server_text_extraction``.

Foundation-model progress is appended page-by-page to ``work_dir/extracted.md``
so an interrupted Sync can resume without redoing finished pages.

Usage:
    from pdf2text import pdf_to_text
    text = pdf_to_text(path, use_foundation_model=False)
"""

from __future__ import annotations

import base64
import logging
import os
import re
import sys
import tempfile
import time
import traceback
from io import BytesIO
from pathlib import Path
from typing import Optional

_GRAPH_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _GRAPH_DIR.parent
_APPLICATION_DIR = _REPO_ROOT / "application"

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_APPLICATION_DIR) not in sys.path:
    sys.path.insert(0, str(_APPLICATION_DIR))
if str(_GRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(_GRAPH_DIR))

logger = logging.getLogger("pdf2text")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}

LLM_PROMPT = (
    "LANGUAGE (mandatory, highest priority):\n"
    "- Detect the primary language of the readable text on the page.\n"
    "- Write the ENTIRE Markdown output in that same language only "
    "(body, headings, lists, captions, figure/table/diagram descriptions, "
    "layout notes, and empty-page remarks).\n"
    "- If the page text is English, the whole output MUST be English. "
    "Do NOT translate into Korean. Do NOT use Korean labels such as "
    "'시각적 요소 설명', '표지', or Korean empty-page messages.\n"
    "- If the page text is Korean, keep the whole output in Korean.\n"
    "- Never mix languages. Never paraphrase into another language.\n\n"
    "Convert the page to Markdown with headings (#/##), lists, emphasis, and "
    "code blocks as appropriate. Exclude top-of-page headers and bottom footers "
    "(e.g. running titles, page numbers).\n\n"
    "If the page has figures, tables, photos, screenshots, or diagrams, describe "
    "what they show and how they relate to the body — in the same language as the "
    "page text."
)

_PAGE_HEADING_RE = re.compile(r"^## Page (\d+)\s*$", re.MULTILINE)
_EXTRACTED_NAME = "extracted.md"
_EXTRACTION_FAIL = "텍스트를 추출하지 못하였습니다."
_MAX_LLM_ATTEMPTS = 3


def _emit_ess_progress(
    file_name: str,
    *,
    page: int | None = None,
    page_n: int | None = None,
    file_i: int | None = None,
    file_n: int | None = None,
    detail: str = "",
) -> None:
    """Print a structured progress line for ESS Sync UI / logs.

    Format::
        [ess progress] name="…" fi=… fn=… p=… pn=… pct=… | human label
    """
    pct: int | None = None
    if page is not None and page_n and page_n > 0:
        pct = max(0, min(100, int(round(100.0 * page / page_n))))
    elif file_i is not None and file_n and file_n > 0:
        pct = max(0, min(100, int(round(100.0 * file_i / file_n))))

    safe = (file_name or "").replace('"', "")
    parts = [f'name="{safe}"']
    if file_i is not None and file_n is not None:
        parts.append(f"fi={file_i}")
        parts.append(f"fn={file_n}")
    if page is not None and page_n is not None:
        parts.append(f"p={page}")
        parts.append(f"pn={page_n}")
    if pct is not None:
        parts.append(f"pct={pct}")

    label_bits = [file_name]
    if file_i is not None and file_n is not None:
        label_bits.append(f"파일 {file_i}/{file_n}")
    if page is not None and page_n is not None:
        label_bits.append(f"페이지 {page}/{page_n}")
    if pct is not None:
        label_bits.append(f"{pct}%")
    if detail:
        label_bits.append(detail)
    human = " · ".join(label_bits)
    print(f"[ess progress] {' '.join(parts)} | {human}", flush=True)


def _vision_max_tokens(model_id: str, model_type: str) -> int:
    mid = (model_id or "").lower()
    if "claude-sonnet-5" in mid or "claude-5-sonnet" in mid or "claude-opus-5" in mid:
        return 128000
    if "claude-4" in mid or "claude-sonnet-4" in mid or "claude-opus-4" in mid:
        return 16384
    if model_type == "openai":
        return 8192
    return 8192


def _get_vision_chat(model_name: str | None = None):
    """Create multimodal chat for page-image → Markdown (Foundation Model Parser).

    Uses the UI-selected model when provided (or ``ESS_VISION_MODEL`` env).

    OpenAI GPT models (``mantle_api=responses``) use Bedrock Mantle + ChatOpenAI,
    matching docgraph-intelligence ``graph/lib/img2text.py``. Claude uses ChatBedrock.
    """
    import boto3
    from botocore.config import Config
    from langchain_aws import ChatBedrock
    from langchain_openai import ChatOpenAI

    import bedrock_data_retention
    import info
    import utils

    config = utils.load_config()
    preferred = (
        (model_name or "").strip()
        or (os.environ.get("ESS_VISION_MODEL") or "").strip()
        or "Claude 5.0 Sonnet"
    )
    models = info.get_model_info(preferred)
    if not models:
        print(
            f"  [foundation model] unknown model {preferred!r}; "
            "falling back to Claude 5.0 Sonnet",
            flush=True,
        )
        preferred = "Claude 5.0 Sonnet"
        models = info.get_model_info(preferred)
    profile = models[0]
    model_id = profile["model_id"]
    model_type = profile["model_type"]
    bedrock_region = profile.get("bedrock_region") or config.get("region", "us-west-2")
    mantle_api = profile.get("mantle_api", "chat")
    max_tokens = _vision_max_tokens(model_id, model_type)

    # OpenAI-on-Bedrock: Mantle Responses API (same as docgraph img2text / chat.py).
    if model_type == "openai" and mantle_api == "responses":

        def bearer_token_provider() -> str:
            return bedrock_data_retention.get_bedrock_bearer_token(bedrock_region)

        print(
            f"  [foundation model] vision model={preferred} id={model_id} "
            f"via=mantle region={bedrock_region}",
            flush=True,
        )
        return ChatOpenAI(
            model=model_id,
            api_key=bearer_token_provider,
            base_url=f"https://bedrock-mantle.{bedrock_region}.api.aws/openai/v1",
            use_responses_api=True,
            max_tokens=max_tokens,
        )

    stop_sequence = "\n\nHuman:" if model_type == "claude" else ""
    boto3_bedrock = boto3.client(
        service_name="bedrock-runtime",
        region_name=bedrock_region,
        config=Config(
            retries={"max_attempts": 30},
            read_timeout=300,
        ),
    )
    parameters: dict = {"max_tokens": max_tokens}
    if model_type == "claude":
        parameters["stop_sequences"] = [stop_sequence]
    chat_kwargs = {
        "model_id": model_id,
        "client": boto3_bedrock,
        "model_kwargs": parameters,
        "region_name": bedrock_region,
    }
    if model_type == "claude":
        chat_kwargs["provider"] = "anthropic"
    print(
        f"  [foundation model] vision model={preferred} id={model_id} "
        f"via=bedrock region={bedrock_region}",
        flush=True,
    )
    return ChatBedrock(**chat_kwargs)


def _prepare_image_base64(
    image_content: bytes,
    max_size: int = 5 * 1024 * 1024,
    max_pixels: int = 2000000,
) -> str:
    """Resize image if needed and return base64 string."""
    from PIL import Image

    img = Image.open(BytesIO(image_content))
    width, height = img.size
    logger.info("Image size: %sx%s, pixels: %s", width, height, width * height)

    is_resized = False
    while width * height > max_pixels:
        width = int(width / 2)
        height = int(height / 2)
        is_resized = True
        logger.info("Resized to %sx%s", width, height)

    if is_resized:
        img = img.resize((width, height))

    for attempt in range(5):
        buffer = BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        img_bytes = buffer.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
        base64_size = len(img_base64.encode("utf-8"))
        logger.info("Attempt %s: base64_size = %s bytes", attempt + 1, base64_size)
        if base64_size <= max_size:
            return img_base64
        width = int(width * 0.8)
        height = int(height * 0.8)
        img = img.resize((width, height))
        logger.info("Resizing to %sx%s due to size limit", width, height)

    raise ValueError("이미지 크기가 너무 큽니다. 5MB 이하의 이미지를 사용해주세요.")


def _content_to_text(content: object) -> str:
    """Normalize LangChain/Bedrock message content to a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()
    return str(content).strip()


def _extract_text_with_llm(img_base64: str, prompt: Optional[str] = None) -> str:
    """Extract text from a page image via Bedrock multimodal.

    Retries up to 3 times on API errors or when the model returns too little text.
    """
    from langchain_core.messages import HumanMessage

    query = prompt or (
        "텍스트를 추출해서 markdown 포맷으로 변환하세요. "
        "원문의 언어를 그대로 유지하고 번역하지 마세요. "
        "<result> tag를 붙여주세요."
    )
    multimodal = _get_vision_chat()
    messages = [
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                },
                {"type": "text", "text": query},
            ]
        )
    ]

    extracted_text = ""
    for attempt in range(1, _MAX_LLM_ATTEMPTS + 1):
        logger.info("LLM attempt: %s/%s", attempt, _MAX_LLM_ATTEMPTS)
        print(
            f"  [foundation model] LLM attempt {attempt}/{_MAX_LLM_ATTEMPTS}",
            flush=True,
        )
        try:
            result = multimodal.invoke(messages)
            extracted_text = _content_to_text(result.content)
            logger.info("LLM text_len=%s", len(extracted_text))
            if len(extracted_text) >= 10:
                break
            logger.warning(
                "LLM returned too little text (len=%s) on attempt %s/%s",
                len(extracted_text),
                attempt,
                _MAX_LLM_ATTEMPTS,
            )
        except Exception as exc:
            logger.warning(
                "LLM error on attempt %s/%s:\n%s",
                attempt,
                _MAX_LLM_ATTEMPTS,
                traceback.format_exc(),
            )
            print(
                f"  [foundation model] LLM error attempt {attempt}/{_MAX_LLM_ATTEMPTS}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            extracted_text = ""
        if attempt < _MAX_LLM_ATTEMPTS:
            time.sleep(1)

    if len(extracted_text) < 10:
        logger.warning(
            "LLM returned too little text after %s attempts (len=%s)",
            _MAX_LLM_ATTEMPTS,
            len(extracted_text),
        )
        extracted_text = _EXTRACTION_FAIL
    return extracted_text


def _parse_result(text: str) -> str:
    """Extract content from <result> tag if present."""
    if text.find("<result>") != -1:
        return text[text.find("<result>") + 8 : text.find("</result>")]
    return text


def pdf_to_images(pdf_path: str | Path, output_dir: str | Path, dpi: int = 150) -> list[str]:
    """Convert every page of *pdf_path* to PNG (rag-multimodal pdf2img).

    Existing ``page_XXX.png`` files are reused (resume-friendly).
    """
    try:
        import pymupdf
    except ImportError:
        import subprocess

        print("PyMuPDF is not installed. Installing pymupdf …", file=sys.stderr)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pymupdf", "-q"],
            stdout=subprocess.DEVNULL,
        )
        import pymupdf

    pdf_path = Path(os.path.expanduser(str(pdf_path))).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(str(pdf_path))
    total = len(doc)
    saved: list[str] = []
    zoom = dpi / 72
    mat = pymupdf.Matrix(zoom, zoom)

    try:
        for i, page in enumerate(doc, start=1):
            out_path = output_dir / f"page_{i:03d}.png"
            if out_path.is_file() and out_path.stat().st_size > 0:
                saved.append(str(out_path.resolve()))
                print(f"  [{i}/{total}] cached → {out_path}", flush=True)
                continue
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(out_path))
            saved.append(str(out_path.resolve()))
            print(f"  [{i}/{total}] Saved → {out_path}", flush=True)
    finally:
        doc.close()

    return saved


def _natural_key(path: Path) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def list_image_files(folder: Path) -> list[Path]:
    out = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    out.sort(key=_natural_key)
    return out


def _extract_image_markdown(image_path: Path) -> str:
    """One page image → Markdown via Bedrock multimodal (built-in helpers)."""
    with open(image_path, "rb") as f:
        raw = f.read()
    b64 = _prepare_image_base64(raw)
    raw_text = _extract_text_with_llm(b64, LLM_PROMPT)
    return _parse_result(raw_text).strip()


def pdf_to_text_classical(path: Path) -> str:
    """Extract plain text with pdfplumber, falling back to pypdf."""
    try:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = (page.extract_text() or "").strip()
                if text:
                    parts.append(f"## Page {i}\n\n{text}")
        if parts:
            return "\n\n".join(parts)
    except Exception as exc:
        print(f"  pdfplumber failed for {path.name}: {exc}; trying pypdf", flush=True)

    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for i, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(f"## Page {i}\n\n{text}")
    return "\n\n".join(parts)


_FAILED_PAGE_MARKERS = (
    "텍스트를 추출하지 못하였습니다.",
    "> (추출 오류:",
    "> (빈 페이지)",
)


def _pages_done_in_md(md_path: Path) -> set[int]:
    """Pages that already have *successful* extraction (skip on resume)."""
    if not md_path.is_file():
        return set()
    text = md_path.read_text(encoding="utf-8", errors="replace")
    done: set[int] = set()
    parts = _PAGE_HEADING_RE.split(text)
    # parts: [preamble, num1, body1, num2, body2, ...]
    i = 1
    while i + 1 < len(parts):
        try:
            page_num = int(parts[i])
        except ValueError:
            i += 2
            continue
        body = (parts[i + 1] or "").strip()
        if body and not any(m in body for m in _FAILED_PAGE_MARKERS):
            done.add(page_num)
        i += 2
    return done


def _append_page_md(md_path: Path, page_num: int, body: str) -> None:
    """Write/replace one ``## Page N`` section and fsync (resume-safe)."""
    section = f"## Page {page_num}\n\n{body.strip()}\n"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    if not md_path.is_file() or md_path.stat().st_size == 0:
        md_path.write_text(section, encoding="utf-8")
        return
    text = md_path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        rf"(^## Page {page_num}\s*\n)(.*?)(?=^## Page \d+\s*$|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(text):
        new_text = pattern.sub(section.rstrip() + "\n", text, count=1)
        md_path.write_text(new_text, encoding="utf-8")
    else:
        with open(md_path, "a", encoding="utf-8") as f:
            f.write("\n" + section)
            f.flush()
            os.fsync(f.fileno())
        return
    with open(md_path, "a", encoding="utf-8") as f:
        f.flush()
        os.fsync(f.fileno())


def pdf_to_text_foundation_model(
    path: Path,
    *,
    work_dir: Path | None = None,
    dpi: int = 150,
    keep_images: bool = False,
) -> str:
    """PDF → page images → multimodal LLM Markdown (Foundation Model Parser).

    Progress is written to ``work_dir/extracted.md`` after each page. Re-runs
    skip pages already present in that file (and reuse existing PNGs).
    """
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    cleanup = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix=f"pdf2text_{path.stem}_"))
        cleanup = not keep_images
    else:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    img_dir = work_dir / "pages"
    extracted_md = work_dir / _EXTRACTED_NAME
    print(
        f"  [foundation model] rendering PDF pages → {img_dir}",
        flush=True,
    )
    try:
        images = pdf_to_images(path, img_dir, dpi=dpi)
        if not images:
            raise ValueError(f"PDF에서 페이지 이미지를 만들지 못했습니다: {path}")

        total_pages = len(images)
        done = _pages_done_in_md(extracted_md)
        if done and len(done) >= total_pages:
            print(
                f"  [foundation model] skip LLM — all {total_pages} page(s) "
                f"already in {extracted_md.name}",
                flush=True,
            )
            _emit_ess_progress(
                path.name,
                page=total_pages,
                page_n=total_pages,
                detail="이미 추출됨 (skip)",
            )
            return extracted_md.read_text(encoding="utf-8", errors="replace").strip()

        if done:
            print(
                f"  [foundation model] resume: {len(done)}/{total_pages} page(s) "
                f"already in {extracted_md.name}",
                flush=True,
            )
            _emit_ess_progress(
                path.name,
                page=len(done),
                page_n=total_pages,
                detail=f"이어하기 {len(done)}/{total_pages}",
            )

        for i, img in enumerate(images, 1):
            if i in done:
                print(
                    f"  [foundation model] [{i}/{total_pages}] skip (already in md)",
                    flush=True,
                )
                continue
            img_path = Path(img)
            print(
                f"  [foundation model] [{i}/{total_pages}] LLM extract {img_path.name}",
                flush=True,
            )
            _emit_ess_progress(
                path.name,
                page=i,
                page_n=total_pages,
                detail="LLM 추출 중",
            )
            try:
                body = _extract_image_markdown(img_path)
            except Exception as exc:
                body = f"> (추출 오류: {exc})"
            if not body:
                body = "> (빈 페이지)"
            _append_page_md(extracted_md, i, body)
            done.add(i)
            _emit_ess_progress(
                path.name,
                page=i,
                page_n=total_pages,
                detail="페이지 완료",
            )

        if not extracted_md.is_file() or extracted_md.stat().st_size == 0:
            raise ValueError(f"Foundation Model Parser가 텍스트를 추출하지 못했습니다: {path}")

        print(
            f"  [foundation model] complete → {extracted_md} "
            f"({len(done)} page(s))",
            flush=True,
        )
        _emit_ess_progress(
            path.name,
            page=total_pages,
            page_n=total_pages,
            detail="변환 완료",
        )
        return extracted_md.read_text(encoding="utf-8", errors="replace").strip()
    finally:
        if cleanup:
            import shutil

            shutil.rmtree(work_dir, ignore_errors=True)


def pdf_to_text(
    path: str | Path,
    *,
    use_foundation_model: bool = False,
    work_dir: Path | None = None,
    dpi: int = 150,
) -> str:
    """Return page-sectioned Markdown/plain text for a PDF.

    When *use_foundation_model* is True, run PDF→images→Bedrock multimodal.
    Otherwise use pdfplumber/pypdf text extraction.

    For foundation model, do **not** fall back to classical on interrupt-style
    failures when partial ``extracted.md`` already exists — re-raise so the
    next Sync can resume. Classical fallback is only for hard startup failures.
    """
    src = Path(path).expanduser().resolve()
    if use_foundation_model:
        work = Path(work_dir) if work_dir else None
        partial = (
            work / _EXTRACTED_NAME
            if work is not None and (work / _EXTRACTED_NAME).is_file()
            else None
        )
        try:
            return pdf_to_text_foundation_model(src, work_dir=work_dir, dpi=dpi)
        except Exception as exc:
            if partial and partial.stat().st_size > 0:
                print(
                    f"  WARNING: foundation model parser interrupted for {src.name}: {exc}; "
                    f"keeping partial {partial} for resume (no classical fallback)",
                    flush=True,
                )
                raise
            print(
                f"  WARNING: foundation model parser failed for {src.name}: {exc}; "
                f"falling back to pdfplumber/pypdf",
                flush=True,
            )
            return pdf_to_text_classical(src)
    return pdf_to_text_classical(src)
