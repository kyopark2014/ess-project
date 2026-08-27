# ess-project / ess

ESS Sync 패키지입니다. Wiki Sync의 **문서 스테이징** 경로를 가져와 PDF→이미지→Markdown
변환을 수행합니다 (`graph/` 지식그래프 빌드는 추후 확장).

## Agent UI

Settings → **ESS** → Sync / Regulations / Configure

| 설정 | 동작 |
|------|------|
| Foundation Model Parser On (기본) | PDF → 페이지 PNG (PyMuPDF) → Bedrock multimodal Markdown |
| Foundation Model Parser Off | pdfplumber / pypdf 텍스트 추출 |

## 핵심 파일

| 파일 | 출처 | 역할 |
|------|------|------|
| `pdf2text.py` | `agent-wiki/graph/pdf2text.py` | PDF→이미지→Markdown / classical 추출 |
| `sync_ess.py` | `sync_wiki.py` 스테이징 로직 | regulations → md/json + FMP intermediates |
| `doc_list.py` | (신규) | `regulations_list.json` / `project_list.json` 문서 레지스트리 관리 |

## 경로

| 항목 | 경로 |
|------|------|
| Regulation 업로드 | `.session_storage/{user}/ess/regulations/` |
| Regulation 문서 목록 | `.session_storage/{user}/ess/regulations_list.json` |
| Project 업로드 | `.session_storage/{user}/ess/projects/` |
| Project 문서 목록 | `.session_storage/{user}/ess/project_list.json` |
| 변환 결과 | 원본과 동일 폴더의 `{stem}.md` + `{stem}.json` |
| FMP 페이지/중간 | `.../out/converted/.pdf_pages/{stem}_{hash}/pages/` + `extracted.md` |

`regulations_list.json` / `project_list.json`은 `ess/doc_list.py`가 관리하며, 문서 추가(업로드)와 Sync 추출 완료 시마다 갱신됩니다.
항목에는 파일명, 생성일, md 파일 위치, 상태 등이 들어갑니다.

업로드 시 파일명은 sanitize됩니다 (공백→`_`, 특수문자 제거). 예: `s9540_3_2025 1.pdf` → `s9540_3_2025_1.pdf`.
원본 이름은 각 list JSON의 `original_filename`에 보관됩니다.

대용량 문서는 RAG/Load files와 같이 **S3 presigned PUT**으로 업로드합니다
(`POST /api/ess/regulations|projects/presign` → browser PUT → `POST /api/ess/.../complete`).

`{stem}.json`에는 파일명, 추출완료시간, 추출한 사람(아이디), 이미지 파일 정보, 원본 PDF 정보 등이 들어갑니다.

## 단독 실행

```bash
cd ess-project
python ess/sync_ess.py --user ksdyb
python ess/sync_ess.py --user ksdyb --full
python ess/doc_list.py --ess-root application/.session_storage/ksdyb/ess --user ksdyb --rebuild
```
