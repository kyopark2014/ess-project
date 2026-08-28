# PDF → Text 추출 과정 (Foundation Model Parser)

ESS Sync에서 PDF를 Markdown으로 변환할 때, **Foundation Model Parser(FMP)** 가 켜져 있으면 PDF를 페이지별 PNG로 렌더링한 뒤 Bedrock vision LLM으로 텍스트를 추출합니다. 구현은 `ess/pdf2text.py`에 있으며, Sync 진입점은 `ess/sync_ess.py` → `pdf_to_text()` 입니다.

## 전체 흐름

```
PDF 파일
  │
  ▼  pdf_to_images()          [PyMuPDF, DPI 150]
pages/page_001.png … page_NNN.png
  │
  ▼  _extract_image_markdown() [페이지당 1회 LLM 호출]
pages/page_NNN.result.md      (Parallel Processing ON)
  │
  ▼  _merge_page_results_to_extracted()
work_dir/extracted.md         (## Page N 섹션으로 조립)
  │
  ▼  sync_ess.py
regulations/{stem}.md + {stem}.json   (소스 옆 최종 산출물)
```

작업 디렉터리 예시 (사용자별):

```
.session_storage/{user}/ess/out/converted/.pdf_pages/{stem}_{hash}/
  source_path.txt
  extracted.md
  pages/
    page_001.png
    page_001.result.md
    page_002.png
    …
```

FMP가 꺼져 있으면 이 경로 대신 `pdf_to_text_classical()`(pdfplumber → pypdf)로 텍스트만 추출합니다.

---

## PDF에서 이미지 추출

### 역할

`pdf_to_images()`가 PyMuPDF(`pymupdf`)로 PDF 각 페이지를 PNG로 렌더링합니다. 기본 DPI는 **150**이며, Sync는 `work_dir/pages/` 아래에 `page_001.png`, `page_002.png`, … 형식으로 저장합니다.

### 핵심 동작

1. PDF를 열고 페이지 수를 확인합니다.
2. `zoom = dpi / 72` 로 스케일 행렬을 만듭니다.
3. 페이지마다 `get_pixmap()` → PNG 저장.
4. **이미 존재하는 PNG는 재사용**합니다 (Sync 중단 후 재개 시 렌더링 생략).

### 핵심 코드

```396:440:ess-project/ess/pdf2text.py
def pdf_to_images(pdf_path: str | Path, output_dir: str | Path, dpi: int = 150) -> list[str]:
    """Convert every page of *pdf_path* to PNG (rag-multimodal pdf2img).

    Existing ``page_XXX.png`` files are reused (resume-friendly).
    """
    ...
    doc = pymupdf.open(str(pdf_path))
    total = len(doc)
    ...
    zoom = dpi / 72
    mat = pymupdf.Matrix(zoom, zoom)

    try:
        for i, page in enumerate(doc, start=1):
            out_path = output_dir / f"page_{i:03d}.png"
            if out_path.is_file() and out_path.stat().st_size > 0:
                saved.append(str(out_path.resolve()))
                ...
                continue
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(out_path))
            saved.append(str(out_path.resolve()))
    finally:
        doc.close()

    return saved
```

`pdf_to_text_foundation_model()`에서 호출됩니다:

```733:742:ess-project/ess/pdf2text.py
    img_dir = work_dir / "pages"
    extracted_md = work_dir / _EXTRACTED_NAME
    ...
    images = pdf_to_images(path, img_dir, dpi=dpi)
    if not images:
        raise ValueError(f"PDF에서 페이지 이미지를 만들지 못했습니다: {path}")
```

---

## 이미지에서 텍스트 추출

### 역할

각 페이지 PNG를 Bedrock multimodal LLM에 보내 Markdown 본문으로 변환합니다. 한 페이지당 `_extract_image_markdown()` → `_prepare_image_base64()` → `_extract_text_with_llm()` 순으로 처리됩니다.

### 처리 단계

| 단계 | 함수 | 설명 |
|------|------|------|
| 1 | `_prepare_image_base64()` | PIL로 리사이즈 (최대 200만 픽셀, base64 5MB 이하) |
| 2 | `_get_vision_chat()` | UI/환경변수 모델 → ChatBedrock 또는 ChatOpenAI(Mantle) |
| 3 | `_extract_text_with_llm()` | 이미지 + 프롬프트를 HumanMessage로 invoke (최대 3회 재시도) |
| 4 | `_parse_result()` | 응답에 `<result>` 태그가 있으면 내부만 추출 |
| 5 | 저장 | Parallel OFF: `extracted.md`에 `## Page N` 섹션 append / Parallel ON: `page_NNN.result.md` |

### LLM 호출 구조

```319:342:ess-project/ess/pdf2text.py
def _extract_text_with_llm(img_base64: str, prompt: Optional[str] = None) -> str:
    ...
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
```

페이지 이미지 → Markdown 진입점:

```453:463:ess-project/ess/pdf2text.py
def _extract_image_markdown(image_path: Path, *, use_llm_semaphore: bool = False) -> str:
    """One page image → Markdown via Bedrock multimodal (built-in helpers)."""
    with open(image_path, "rb") as f:
        raw = f.read()
    b64 = _prepare_image_base64(raw)
    if use_llm_semaphore:
        with _get_llm_semaphore():
            raw_text = _extract_text_with_llm(b64, LLM_PROMPT)
    else:
        raw_text = _extract_text_with_llm(b64, LLM_PROMPT)
    return _parse_result(raw_text).strip()
```

### 프롬프트 위치 및 내용

**위치:** `ess/pdf2text.py` 상단 모듈 상수 `LLM_PROMPT` (51~68행)

FMP 경로에서는 `_extract_image_markdown()`이 이 상수를 `_extract_text_with_llm(b64, LLM_PROMPT)`로 전달합니다. `prompt` 인자를 넘기지 않는 한 아래 fallback(326~330행의 한국어 짧은 프롬프트)은 **사용되지 않습니다**.

**현재 사용 중인 프롬프트 (`LLM_PROMPT`):**

```
LANGUAGE (mandatory, highest priority):
- Detect the primary language of the readable text on the page.
- Write the ENTIRE Markdown output in that same language only
  (body, headings, lists, captions, figure/table/diagram descriptions,
  layout notes, and empty-page remarks).
- If the page text is English, the whole output MUST be English.
  Do NOT translate into Korean. Do NOT use Korean labels such as
  '시각적 요소 설명', '표지', or Korean empty-page messages.
- If the page text is Korean, keep the whole output in Korean.
- Never mix languages. Never paraphrase into another language.

Convert the page to Markdown with headings (#/##), lists, emphasis, and
code blocks as appropriate. Exclude top-of-page headers and bottom footers
(e.g. running titles, page numbers).

If the page has figures, tables, photos, screenshots, or diagrams, describe
what they show and how they relate to the body — in the same language as the
page text.
```

소스 코드상 정의:

```51:68:ess-project/ess/pdf2text.py
LLM_PROMPT = (
    "LANGUAGE (mandatory, highest priority):\n"
    "- Detect the primary language of the readable text on the page.\n"
    ...
    "page text."
)
```

### 최종 Markdown 조립

Parallel Processing이 꺼져 있을 때는 페이지마다 `_append_page_md()`로 `extracted.md`에 `## Page N` 섹션을 추가합니다.

```522:524:ess-project/ess/pdf2text.py
def _append_page_md(md_path: Path, page_num: int, body: str) -> None:
    """Write/replace one ``## Page N`` section and fsync (resume-safe)."""
    section = f"## Page {page_num}\n\n{body.strip()}\n"
```

Sync가 완료되면 `sync_ess.py`가 `extracted.md` 내용을 `{stem}.md` / `{stem}.json`으로 소스 파일 옆에 기록합니다.

---

## 이미지에서 텍스트 전환 실패

### 왜 실패하는가

NFPA 855, 화재 안전 설계, ESS 소화 설비 등 **화재·안전 관련 문서** 페이지에는 그림, 경고 문구, 사고 시나리오, 규격 표 등이 포함됩니다. Bedrock vision LLM(Claude/GPT)은 콘텐츠 정책에 따라 이런 이미지를 **거부(refusal)** 하거나, API 예외·지나치게 짧은 응답으로 **추출을 차단**할 수 있습니다.

코드는 “차단” 여부를 별도 분류하지 않고, 아래 조건이면 **같은 페이지에 대해 최대 3회** 재시도한 뒤 실패로 처리합니다.

- `multimodal.invoke()` 예외 (rate limit, validation, 정책 거부 등)
- 응답 텍스트 길이가 **10자 미만** (빈 응답·거부에 가까운 경우)

### 3회 재시도 후 실패 처리

재시도 상한은 모듈 상수 `_MAX_LLM_ATTEMPTS = 3` 입니다.

```72:72:ess-project/ess/pdf2text.py
_MAX_LLM_ATTEMPTS = 3
```

```344:386:ess-project/ess/pdf2text.py
    extracted_text = ""
    for attempt in range(1, _MAX_LLM_ATTEMPTS + 1):
        ...
        try:
            result = multimodal.invoke(messages)
            extracted_text = _content_to_text(result.content)
            if len(extracted_text) >= 10:
                break
            ...
        except Exception as exc:
            ...
            extracted_text = ""
        if attempt < _MAX_LLM_ATTEMPTS:
            time.sleep(1)

    if len(extracted_text) < 10:
        ...
        extracted_text = _EXTRACTION_FAIL
    return extracted_text
```

3회 모두 실패하면 본문 대신 **`텍스트를 추출하지 못하였습니다.`** (`_EXTRACTION_FAIL`)가 반환됩니다.

```72:72:ess-project/ess/pdf2text.py
_EXTRACTION_FAIL = "텍스트를 추출하지 못하였습니다."
```

이 문자열과 `> (추출 오류: …)`, `> (빈 페이지)`는 **실패 마커**로 등록되어 있어, Sync 재실행 시 해당 페이지는 **완료로 간주되지 않고** 다시 LLM 추출을 시도합니다.

```493:497:ess-project/ess/pdf2text.py
_FAILED_PAGE_MARKERS = (
    "텍스트를 추출하지 못하였습니다.",
    "> (추출 오류:",
    "> (빈 페이지)",
)
```

Parallel Processing 경로에서는 예외 시 `> (추출 오류: {exc})` 형태로 temp에 기록됩니다.

```657:662:ess-project/ess/pdf2text.py
        try:
            body = _extract_image_markdown(img_path, use_llm_semaphore=True)
        except Exception as exc:
            body = f"> (추출 오류: {exc})"
        if not body:
            body = "> (빈 페이지)"
```

### 대응 방법

동일 페이지에서 실패가 **반복**되면 다음을 시도하세요.

1. **다른 vision 모델로 Sync** — 사이드바에서 Claude ↔ GPT 계열을 **교차** 선택한 뒤 ESS Sync를 다시 실행합니다. 모델마다 콘텐츠 정책·거부 패턴이 다릅니다.
2. **실패 페이지만 재시도** — 실패 마커가 있는 페이지는 resume 로직상 자동으로 pending에 남습니다. 모델만 바꿔 Sync하면 해당 페이지부터 다시 호출됩니다.
3. **Foundation Model Parser Off** — 정책 차단이 아닌 “텍스트 레이어가 있는 PDF”라면 classical(pdfplumber/pypdf) 경로로 우회할 수 있습니다 (스캔 PDF·도면은 품질이 떨어질 수 있음).

### 이미지에서 텍스트 모델의 선택

ESS Sync의 **페이지 이미지 → Markdown** 변환에 쓰는 vision 모델은 **UI에서 선택**합니다. ESS Configure의 Foundation Model Parser / Parallel Processing과 별개로, **사이드바 Settings → Model**에 표시된 **현재 태스크의 모델**이 Sync 시 vision 모델로 전달됩니다.

**UI → API → Sync subprocess 흐름**

1. 사용자가 Model 드로어에서 `Claude 4.6 Sonnet`, `GPT …` 등 display name 선택 (태스크 `model_name` 저장)
2. ESS **Sync** 실행 시 그 이름을 query parameter `model`로 POST
3. 백그라운드 job이 `sync_ess.py --model "…"` 및 환경변수 `ESS_VISION_MODEL` 설정
4. `pdf2text._get_vision_chat()`이 `ESS_VISION_MODEL` → `info.get_model_info()`로 Bedrock `model_id`·`model_type` 해석

**프론트엔드 — Sync 시 현재 모델 전달**

```117:117:ess-project/application/web/src/components/Sidebar.tsx
  const modelName = activeTask?.model_name ?? config?.default_model ?? "";
```

```201:202:ess-project/application/web/src/components/Sidebar.tsx
      const result = await api.syncEss(false, modelName || undefined);
```

```540:547:ess-project/application/web/src/api.ts
  syncEss: (full = false, model?: string) => {
    const params = new URLSearchParams();
    if (full) params.set("full", "1");
    if (model?.trim()) params.set("model", model.trim());
    ...
    return request<EssStatus>(`/api/ess/sync${qs ? `?${qs}` : ""}`, {
      method: "POST",
    });
  },
```

**API — Sync 엔드포인트**

```1276:1289:ess-project/application/api/routes_ess.py
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
    ...
    job = ensure_ess_sync(user_id, full=full, model=model)
```

**백그라운드 job — subprocess에 모델 주입**

```367:377:ess-project/application/ess_jobs.py
        cmd = [sys.executable, "-u", str(_SYNC_SCRIPT), "--user", user_id]
        ...
        if model_name:
            cmd.extend(["--model", model_name])
        ...
        if model_name:
            env["ESS_VISION_MODEL"] = model_name
```

**Sync 스크립트 — 환경변수 설정**

```757:760:ess-project/ess/sync_ess.py
    model_name = (model or "").strip()
    if model_name:
        os.environ["ESS_VISION_MODEL"] = model_name
        print(f"ESS vision model: {model_name}", flush=True)
```

**pdf2text — 모델 프로필 → ChatBedrock / ChatOpenAI**

```171:254:ess-project/ess/pdf2text.py
def _get_vision_chat(model_name: str | None = None):
    ...
    preferred = (
        (model_name or "").strip()
        or (os.environ.get("ESS_VISION_MODEL") or "").strip()
        or "Claude 5.0 Sonnet"
    )
    models = info.get_model_info(preferred)
    ...
    profile = models[0]
    model_id = profile["model_id"]
    model_type = profile["model_type"]
    ...
    if model_type == "openai" and mantle_api == "responses":
        return ChatOpenAI(...)
    ...
    return ChatBedrock(**chat_kwargs)
```

| `model_type` | 클라이언트 | 비고 |
|--------------|-----------|------|
| `claude` | `ChatBedrock` | Bedrock Invoke (Anthropic) |
| `openai` (`mantle_api=responses`) | `ChatOpenAI` | Bedrock Mantle Responses API |

UI에서 모델을 지정하지 않으면 기본값 **`Claude 5.0 Sonnet`** 이 사용됩니다. 화재 관련 페이지에서 한 모델이 반복 실패하면, **Claude 계열과 GPT 계열을 번갈아** 선택한 뒤 Sync를 다시 실행하는 것이 권장됩니다.

---

## Parallel Processing

### 개요

ESS Configure의 **Parallel Processing** 옵션(기본 On, `ess_parallel_processing_enabled`)과 Foundation Model Parser가 **모두 켜져 있을 때** 페이지 LLM 추출이 병렬로 실행됩니다. `sync_ess.py`가 `parallel_pages=True`로 `pdf_to_text()`를 호출합니다.

### per-page temp + merge

병렬 worker가 같은 `extracted.md`에 동시에 쓰면 파일이 깨질 수 있으므로, 각 페이지 결과는 먼저 개별 temp 파일에 저장합니다.

| 파일 | 의미 |
|------|------|
| `pages/page_NNN.result.md` | N번 페이지 LLM 추출 결과 (resume용) |
| `extracted.md` | 모든 페이지를 `## Page N` 순으로 merge한 최종본 |

temp 파일 경로:

```103:104:ess-project/ess/pdf2text.py
def _page_result_path(pages_dir: Path, page_num: int) -> Path:
    return pages_dir / f"page_{page_num:03d}{_PAGE_RESULT_SUFFIX}"
```

merge:

```608:622:ess-project/ess/pdf2text.py
def _merge_page_results_to_extracted(
    extracted_md: Path, pages_dir: Path, total_pages: int
) -> None:
    """Assemble ``extracted.md`` from per-page temp files (page order)."""
    sections: list[str] = []
    for page_num in range(1, total_pages + 1):
        body = _read_page_body(pages_dir, extracted_md, page_num)
        if not body:
            body = "> (빈 페이지)"
        sections.append(f"## Page {page_num}\n\n{body.strip()}\n")
    extracted_md.write_text("".join(sections), encoding="utf-8")
```

### 병렬 실행

`_extract_pages_parallel()`이 미완료 페이지만 `ThreadPoolExecutor`에 넣습니다.

```625:687:ess-project/ess/pdf2text.py
def _extract_pages_parallel(...) -> set[int]:
    pending = [i for i in range(1, total_pages + 1) if i not in done]
    workers = min(_page_workers(), len(pending))
    ...
    def _process_page(page_num: int) -> tuple[int, str]:
        ...
        body = _extract_image_markdown(img_path, use_llm_semaphore=True)
        ...
        _write_page_result(img_dir, page_num, body)
        return page_num, body

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process_page, page_num): page_num for page_num in pending}
        for fut in as_completed(futures):
            ...
            _emit_ess_progress(..., aggregated=True)

    _merge_page_results_to_extracted(extracted_md, img_dir, total_pages)
    return done
```

**동시성 제어**

| 설정 | 환경변수 | 기본값 | 의미 |
|------|----------|--------|------|
| Page workers | `ESS_SYNC_PAGE_WORKERS` | 4 | PDF당 thread pool 크기 |
| LLM 동시 호출 | `ESS_SYNC_LLM_CONCURRENCY` | 4 | 전역 semaphore (`_get_llm_semaphore()`) |

Bedrock rate limit(429)을 피하기 위해 worker 수와 LLM 동시 호출 수를 분리해 캡합니다.

### Resume (중단 재개)

완료된 페이지는 `_collect_done_pages()`로 판별합니다. `extracted.md`의 성공 섹션과 `page_NNN.result.md` temp를 **합집합**으로 보며, 실패 마커(`텍스트를 추출하지 못하였습니다.`, `> (추출 오류:`, `> (빈 페이지)`)가 있는 페이지는 미완료로 간주해 재시도합니다.

```566:572:ess-project/ess/pdf2text.py
def _collect_done_pages(
    extracted_md: Path, pages_dir: Path, total_pages: int
) -> set[int]:
    """Pages with successful extraction in ``extracted.md`` or per-page temps."""
    done = _pages_done_in_md(extracted_md)
    done.update(_pages_done_from_temps(pages_dir, total_pages))
    return done
```

### Progress UI 집계

병렬 모드에서는 페이지 **번호**가 아니라 **완료 개수**를 progress로 보냅니다. `[ess progress]` 라인에 `agg=1`, `p=완료수`, `pn=전체`가 포함되며, Sync 모달에는 `완료 12/286 페이지` 형태로 표시됩니다.

```676:684:ess-project/ess/pdf2text.py
                _emit_ess_progress(
                    path.name,
                    page=done_count,
                    page_n=total_pages,
                    ...
                    aggregated=True,
                )
```

Parallel Processing을 끄면(`parallel_pages=False`) 기존처럼 페이지를 **순차** 처리하고 `extracted.md`에 직접 append합니다.

---

## 참고: public API

```python
from pdf2text import pdf_to_text

# Classical (FMP Off)
text = pdf_to_text(path, use_foundation_model=False)

# Foundation Model Parser (Parallel Processing은 sync 설정에 따름)
text = pdf_to_text(
    path,
    use_foundation_model=True,
    work_dir=Path(".../.pdf_pages/{stem}_{hash}"),
    parallel_pages=True,
    file_i=1,
    file_n=5,
)
```
