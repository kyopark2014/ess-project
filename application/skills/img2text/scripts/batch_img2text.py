#!/usr/bin/env python3
"""
Batch image→Markdown using the same pipeline as mcp_server_text_extraction.py.
Run from the application/ directory:

    python skills/img2text/scripts/batch_img2text.py "<folder_with_images>"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# application/ is parent of skills/
_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

import mcp_server_text_extraction as tex  # noqa: E402

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


def natural_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def list_image_files(folder: Path) -> list[Path]:
    out = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    out.sort(key=natural_key)
    return out


def extract_one(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        raw = f.read()
    b64 = tex._prepare_image_base64(raw)
    raw_text = tex._extract_text_with_llm(b64, LLM_PROMPT)
    return tex._parse_result(raw_text).strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="폴더 내 이미지를 LLM으로 Markdown 변환 후 폴더명.md로 저장"
    )
    parser.add_argument("folder", type=Path, help="이미지가 들어 있는 폴더 경로")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="출력 .md 경로 (기본: 폴더 안의 폴더이름.md)",
    )
    args = parser.parse_args()

    folder = args.folder.expanduser().resolve()
    if not folder.is_dir():
        print(f"Error: 폴더가 아닙니다: {folder}", file=sys.stderr)
        return 1

    images = list_image_files(folder)
    if not images:
        print(f"Error: 이미지 파일이 없습니다: {folder}", file=sys.stderr)
        return 1

    out_path = args.output.expanduser().resolve() if args.output else folder / f"{folder.name}.md"

    parts: list[str] = []
    for i, img in enumerate(images, start=1):
        print(f"[{i}/{len(images)}] {img.name}", file=sys.stderr)
        try:
            body = extract_one(img)
        except Exception as e:
            body = f"> (추출 오류: {e})"
        parts.append(f"## 파일: {img.name}\n\n{body}\n")

    text = "\n".join(parts).rstrip() + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
