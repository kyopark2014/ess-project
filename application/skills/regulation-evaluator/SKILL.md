---
name: regulation-evaluator
description: >
  규격 테스트케이스 JSON과 분석 대상 보고서(Markdown)를 함께 받아 조항별 적합성(합격/부분합격/불합격/확인불가/해당없음)을
  판정하고 Excel 컴플라이언스 리포트를 생성한다. ERG·부품명세·설계시방·EOP 등 문서 유형에 무관하게 동작한다.
  대상 md를 먼저 읽고, JSON의 test case를 하나씩 검증한다. 규격 세부 내용이 필요하면 knowledge base MCP retrieve를 호출한다.
  출력은 ARTIFACTS_DIR/reports/ 아래 4시트 Excel(Summary, 판정결과_상세, 조치필요_항목, 문서_커버리지_매핑)이다.
  트리거: regulation-evaluator, 적합성 검토, 컴플라이언스 리포트, 규격 평가, testcase로 보고서 검증,
  NFPA/UL 적합성, Fire Safety Spec, ERG, 합격·불합격 판정 리포트, testcase json + md 동시 첨부.
---

# regulation-evaluator

규격 **테스트케이스 JSON**으로 **대상 Markdown 문서**의 적합성을 평가하고 Excel 리포트를 만든다.  
문서 유형(ERG, Fire Safety Component Spec, 설계시방, EOP, SDS 등)에 **종속되지 않는 범용** 워크플로우다.

## 입력

채팅에 **두 파일을 함께** 첨부(또는 경로 제공)한다.

| 입력 | 형식 | 역할 |
|------|------|------|
| 테스트케이스 | `.json` (`cases` 배열) | 규격 조항·원문·판정 기준 |
| 분석 대상 | `.md` | 검증할 문서 (유형 무관) |

파일이 하나뿐이거나 경로가 불명확하면 중단하고 두 입력을 요청한다.

## 판정값

| 판정결과 | 의미 |
|----------|------|
| `합격` | 대상 문서에서 요구사항 충족이 **명확히** 확인됨 |
| `부분합격` | 일부만 충족·언급. 누락·미확인 남음 |
| `불합격` | 문서상 **미충족** 확인 |
| `확인불가` | 문서 범위 밖(현장·별도 문서 필요) |
| `해당없음` | 제품/설치 유형상 미적용 |

## 워크플로우

```
- [ ] 1. 입력 확인 (json + md)
- [ ] 2. 대상 md 전체 읽기 · 문서 유형/범위 파악 (범용)
- [ ] 3. cases 선별 (문서 범위에 맞게)
- [ ] 4. 조항별 평가 (필요 시 retrieve)
- [ ] 5. 평가 JSON 저장 (필수 키·별칭 준수)
- [ ] 6. generate_compliance_report.py 실행
- [ ] 7. upload_file_to_s3 + 요약
```

### 1–2. 입력 · 대상 문서 먼저 읽기

JSON보다 **대상 md를 먼저** 읽는다. ERG 전제 금지.

파악 항목 (문서에서 있으면 채움, 없으면 빈 문자열 허용하되 meta에 명시):

- 문서 유형·제목·버전
- 제품명·배터리 타입·제조사 (있으면)
- 섹션/페이지 구조 → 커버리지 매핑
- 이 문서로 **검증 가능한 주제** vs **범위 밖 주제**

출력 파일명: `{standard_slug}_{doc_stem}_Compliance_Report.xlsx`  
**동일 파일이 `ARTIFACTS_DIR/reports/`에 있으면 스크립트가 자동으로**  
`…_Compliance_Report_1.xlsx`, `…_Compliance_Report_2.xlsx` … 로 저장한다 (덮어쓰기 금지).

### 3. Test case 선별

전체 cases가 많으면 **이 문서로 검증 가능한 조항만** 평가한다.  
예: 부품명세 → 감지·경보·환기/방폭·부품인증; ERG → 비상계획·위험고지·대응절차.  
범위 밖 조항은 제외하거나 `확인불가`/`해당없음`으로만 짧게 처리.

### 4. 조항별 평가

1. `항목`·`원문`·`기준` 확인  
2. 대상 md에서 근거 검색  
3. 참조 규격 세부 필요 시 `retrieve(keyword="…")`  
4. **판정결과 + 판정근거(문서 인용) + 비고**를 반드시 분리해 기록

근거에는 페이지/섹션/부품명을 적는다. `비고`에는 후속 조치만.

### 5. 평가 JSON (필수)

경로: `$ARTIFACTS_DIR/reports/<stem>_evaluation.json`  
상세·별칭: [references/report-format.md](references/report-format.md)

**정규화 전 권장 키(에이전트가 이걸 쓰면 가장 안전):**

```json
{
  "meta": {
    "title": "{규격} 적합성 검토 리포트 — {문서명}",
    "target_doc": "문서 파일명/제목",
    "standard": "NFPA 855 (2023)",
    "product": "제품명 (없으면 \"\")",
    "battery_type": "있으면 기입, 없으면 \"\"",
    "review_date": "YYYY-MM-DD",
    "scope": "이 문서로 검증한 범위 한 줄",
    "output_name": "….xlsx",
    "coverage_sheet_name": "문서_커버리지_매핑"
  },
  "summary": {
    "strengths": ["…"],
    "gaps": ["…"],
    "needs_verification": ["…"]
  },
  "results": [
    {
      "chapter": "Chapter 4.8",
      "규격명": "NFPA 855 (2023)",
      "항목": "4.8.1",
      "원문": "…",
      "기준": "…",
      "판정결과": "합격",
      "판정근거": "문서 Page/Section 인용",
      "비고": ""
    }
  ],
  "actions": [
    {
      "항목": "4.8.3",
      "요구사항": "규격이 요구하는 내용 요약",
      "현재상태": "문서에서 확인된 상태",
      "권고조치": "다음에 할 일",
      "우선순위": "높음"
    }
  ],
  "coverage": [
    {
      "섹션": "문서 섹션/페이지명",
      "주요내용": "그 섹션이 다루는 내용",
      "관련조항": "4.8.1, 9.6.1",
      "커버리지": "잘 커버"
    }
  ]
}
```

필수:

- `results[]`마다 **`판정근거` 비우지 말 것** (합격·부분합격·확인불가 모두)
- `actions[]`에 **`요구사항`·`현재상태`·`권고조치` 모두** 채울 것 (항목·우선순위만 금지)
- `coverage[]`에 **섹션·관련조항·커버리지** 채울 것 (`잘 커버`/`부분 커버`/`미커버`)
- `summary.gaps` / `needs_verification` 비우지 말 것 (해당 없으면 빈 배열 `[]`)

스크립트가 `근거`→`판정근거`, `조치사항`→`권고조치`, `target_document`→`target_doc` 등 별칭을 정규화하지만, **위 권장 키를 우선** 사용한다.

### 6. Excel 생성

**반드시** 아래 스크립트로만 xlsx를 만든다.  
`execute_code`에서 `wb.save(f"{ARTIFACTS_DIR}/reports/…_Compliance_Report.xlsx")` 금지 (동일 이름 덮어쓰기·빈 CF 링크 원인).

```bash
cd application
python skills/regulation-evaluator/scripts/generate_compliance_report.py \
  --evaluation "$ARTIFACTS_DIR/reports/<stem>_evaluation.json" \
  --output-name "<stem>_Compliance_Report.xlsx" \
  --user "<user_id>"
```

스크립트 동작:

1. `ARTIFACTS_DIR/reports/<stem>_Compliance_Report.xlsx` 경로를 잡는다  
2. **파일이 이미 있으면** `<stem>_Compliance_Report_1.xlsx`, `_2`, … 로 저장  
3. stdout JSON의 **`path`**(실제 저장된 경로)를 확인한다

시트: `Summary` / `판정결과_상세` / `조치필요_항목` / `{coverage_sheet_name}`

### 7. 업로드 · 보고

1. **`upload_file_to_s3`에는 6단계 stdout의 `path`만** 넘긴다  
   (`--output-name` 원본 이름을 하드코딩하면 예전 파일을 올릴 수 있음)
2. 반환된 CloudFront URL과 함께 집계·강점·우선 보완 요약

## 조치 우선순위

| 값 | 표시 | 기준 |
|----|------|------|
| 높음 | `⭐⭐⭐ 높음` | 안전·인증 핵심 누락 |
| 중간 | `⭐⭐ 중간` | 시험보고·사양·계산서 보완 |
| 낮음 | `⭐ 낮음` | 현장·범위 밖 확인 |

## 금지

- ERG 전용 라벨/예시를 다른 문서에 그대로 쓰지 말 것  
- 대상 md에 없는 내용을 있다고 단정하지 말 것  
- 전체 TC 무조건 전부 채점 금지 — 문서 범위 선별  
- Excel을 `execute_code`의 `wb.save(…_Compliance_Report.xlsx)`로 직접 저장 금지 — **스크립트만 사용**  
- 업로드 경로를 `…_Compliance_Report.xlsx`로 고정하지 말 것 — **스크립트가 준 `path` 사용**
