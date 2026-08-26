# ess-project / ess

ESS Sync 패키지입니다. Wiki Sync의 **문서 스테이징** 경로를 가져와 PDF→이미지→Markdown
변환을 수행합니다 (`graph/` 지식그래프 빌드는 추후 확장).

## Agent UI

Settings → **ESS** → Sync / Configure

| 설정 | 동작 |
|------|------|
| Foundation Model Parser On (기본) | PDF → 페이지 PNG (PyMuPDF) → Bedrock multimodal Markdown |
| Foundation Model Parser Off | pdfplumber / pypdf 텍스트 추출 |

## 위키에서 가져온 핵심 파일

| 파일 | 출처 | 역할 |
|------|------|------|
| `pdf2text.py` | `agent-wiki/graph/pdf2text.py` | PDF→이미지→Markdown / classical 추출 |
| `sync_ess.py` | `sync_wiki.py` 스테이징 로직 | raw → `out/converted/` |

## 경로

| 항목 | 경로 |
|------|------|
| 업로드 | `.session_storage/{user}/ess/raw/` |
| 변환 결과 | `.session_storage/{user}/ess/out/converted/*.md` |
| FMP 페이지/중간 | `.../converted/.pdf_pages/{stem}_{hash}/pages/` + `extracted.md` |

## 단독 실행

```bash
cd ess-project
python ess/sync_ess.py --user ksdyb
python ess/sync_ess.py --user ksdyb --full
```
