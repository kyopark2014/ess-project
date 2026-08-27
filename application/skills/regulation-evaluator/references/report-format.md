# 컴플라이언스 Excel 리포트 형식 (범용)

문서 유형(ERG, 부품명세, 설계시방 등)과 무관하게 동일 시트 구조를 쓴다.  
예: `NFPA855_FS05_Compliance_Report.xlsx`, `NFPA855_F2XX_ERG_Compliance_Report.xlsx`

## 평가 JSON — 권장 키

```json
{
  "meta": {
    "title": "{표준} 적합성 검토 리포트 — {문서명}",
    "target_doc": "대상 문서 제목/파일명",
    "standard": "NFPA 855 (2023) …",
    "product": "제품명 또는 \"\"",
    "battery_type": "있으면 기입, 없으면 \"\"",
    "review_date": "YYYY-MM-DD",
    "scope": "이 문서로 검증한 범위",
    "output_name": "….xlsx",
    "coverage_sheet_name": "문서_커버리지_매핑",
    "coverage_title": "문서 섹션 ↔ 규격 조항 커버리지 매핑",
    "evidence_col_label": "판정 근거 (대상 문서 근거)",
    "action_req_label": "규격 요구사항",
    "action_status_label": "현재 문서 상태"
  },
  "summary": {
    "strengths": ["강점 문장"],
    "gaps": ["보완 필요 문장"],
    "needs_verification": ["별도 확인 문장"]
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
      "요구사항": "규격 요구 요약",
      "현재상태": "문서에서 본 상태",
      "권고조치": "후속 조치",
      "우선순위": "높음"
    }
  ],
  "coverage": [
    {
      "섹션": "문서 섹션명",
      "주요내용": "섹션 요약",
      "관련조항": "4.8.1, 9.6.1",
      "커버리지": "잘 커버"
    }
  ]
}
```

## 스크립트가 인식하는 별칭

생성 스크립트(`generate_compliance_report.py`)가 로드 시 정규화한다.

| 정규 키 | 허용 별칭 |
|---------|-----------|
| `meta.target_doc` | `target_document`, `document`, `doc_name` |
| `meta.review_date` | `evaluated_at` (`auto` → 오늘) |
| `meta.scope` | `excluded_note`, `doc_type` |
| `summary.gaps` | `improvements`, `보완`, `보완필요` |
| `summary.needs_verification` | `needs_check`, `별도확인`, `out_of_scope` |
| `results[].판정근거` | `근거`, `evidence`, `rationale`, `reason` |
| `results[].기준` | `판정 기준`, `criteria` |
| `actions[].권고조치` | `권고 조치사항`, `조치사항`, `action`, `recommendation` |
| `actions[].요구사항` | `규격 요구사항`, `requirement`, `기준`, `요약` |
| `actions[].현재상태` | `현재 문서 상태`, `status`, `근거`, `판정근거` |
| `coverage[].섹션` | `문서_섹션`, `문서섹션`, `section`, `doc_section` |
| `coverage[].관련조항` | `대응_조항`, `대응조항`, `clauses` |
| `coverage[].커버리지` | `평가`, `coverage`, `rating` |
| `coverage[].주요내용` | `주요 내용`, `내용`, `content` (없으면 평가 문구 사용) |

`actions`가 비어 있으면 `부분합격`/`불합격`/`확인불가` results에서 자동 생성한다.  
`summary.gaps` / `needs_verification` / `strengths`가 비면 results에서 유도한다.

커버리지 `평가` 자유 문구도 매핑한다: 합격/핵심→잘 커버, 부분/확인→부분 커버, 미포함/범위 밖→미커버.

## 시트 구조

### Summary
메타 6행 + 판정 집계 + 강점/보완/별도확인

### 판정결과_상세
`규격명 | 항목 | 원문 (요약) | 판정 기준 | 판정결과 | {evidence_col_label} | 비고`

### 조치필요_항목
`항목 | {action_req_label} | {action_status_label} | 권고 조치사항 | 우선순위`

### 커버리지 매핑
시트명 `coverage_sheet_name` (기본 `문서_커버리지_매핑`)  
`문서 섹션 | 주요 내용 | 관련 규격 조항 | 커버리지 평가`

## 색상

| 키 | hex |
|----|-----|
| header_bg | `1F4E79` |
| pass | `C6EFCE` / `006100` |
| partial | `FFEB9C` / `9C5700` |
| fail | `FFC7CE` / `9C0006` |
| unknown | `D9D9D9` |
| na | `DDEBF7` |
| chapter | `D6DCE4` |

폰트: `맑은 고딕`. 항상 새 `Font`/`PatternFill` 인스턴스.
