# 공식 기록 검토와 독립검수

이 설정은 검수 담당자를 위한 것입니다. 프로그램은 현재 API 매핑만으로 과거 법인이나 정정 버전을 승인하지 않습니다. 근거 없는 `true` 입력은 검증이 아니며 `READY`를 만들기 위해 빈 근거를 작성해서는 안 됩니다.

`config/reviews.json`은 관리자 파일이며 Git·평가용 ZIP에서 제외합니다. 근거는 `config/evidence/` 아래에 보관합니다. 각 항목에는 검토자·검토일, 공식 URL, 당시 자료 공개일, 근거 파일 경로·SHA256이 있어야 합니다. 현재 파일을 검토한 시점은 `reviewed_at`, 원래 공시의 공개일은 `publication_date`로 구분합니다. API 키가 포함된 URL은 허용하지 않습니다. 파일 해시만으로 공식 출처를 증명할 수 없으므로 검수자가 출처의 진위를 별도로 확인해야 합니다.

형식 예시는 아래와 같습니다. `REPLACE_...` 값은 실제 검토 결과로 바꿔야 하며 예시 그대로는 승인되지 않습니다.

```json
{
  "identities": {
    "000140": {
      "asof": "2019-09-18",
      "corp_code": "REPLACE_8_DIGITS",
      "historical_name": "REPLACE_VERIFIED_HISTORICAL_NAME",
      "stock_code_continuity_checked": true,
      "corporate_actions_checked": true,
      "historical_name_checked": true,
      "reviewed_by": "REPLACE_REVIEWER",
      "reviewed_at": "REPLACE_REVIEW_DATE",
      "evidence": [{
        "path": "config/evidence/identity-record.html",
        "sha256": "REPLACE_64_HEX_DIGITS",
        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=REPLACE_RECEIPT",
        "publication_date": "REPLACE_ORIGINAL_PUBLICATION_DATE"
      }]
    }
  },
  "documents": {
    "REPLACE_14_DIGIT_RECEIPT": {
      "asof": "2019-09-18",
      "corp_code": "REPLACE_8_DIGITS",
      "stock_code": "000140",
      "receipt_no": "REPLACE_14_DIGIT_RECEIPT",
      "reporting_period": "2018-12",
      "document_type": "annual",
      "raw_sha256": "REPLACE_EXACT_DOWNLOADED_ZIP_SHA256",
      "receipt_checked": true,
      "corporation_checked": true,
      "period_checked": true,
      "historical_version_checked": true,
      "full_content_checked": true,
      "attachments_checked": true,
      "missing_attachments": [],
      "reviewed_by": "REPLACE_REVIEWER",
      "reviewed_at": "REPLACE_REVIEW_DATE",
      "evidence": [{
        "path": "config/evidence/document-record.html",
        "sha256": "REPLACE_EVIDENCE_SHA256",
        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=REPLACE_RECEIPT",
        "publication_date": "REPLACE_ORIGINAL_PUBLICATION_DATE"
      }]
    }
  },
  "history": {
    "available_from": "1999-01-01",
    "earliest_available_checked": true,
    "reviewed_by": "REPLACE_REVIEWER",
    "reviewed_at": "REPLACE_REVIEW_DATE",
    "evidence": [{
      "path": "config/evidence/historical-coverage.html",
      "sha256": "REPLACE_EVIDENCE_SHA256",
      "source_url": "https://dart.fss.or.kr/",
      "publication_date": "REPLACE_ORIGINAL_HISTORICAL_SOURCE_DATE"
    }]
  }
}
```

사업보고서는 `annual`, 반기·분기는 `interim`입니다. 정정 문서에는 같은 항목 외에 `correction_parent`(직전 문서의 접수번호), `correction_relation_checked: true`가 필요합니다. 정정 체인의 각 접수번호에 관계 확인 근거가 있어야 합니다. 체인 안의 회계기간이 다르거나 접수 순서가 뒤집히거나 같은 기간에 연결되지 않은 공시가 있으면 승인하지 않습니다. 철회나 불명확한 보고기간도 검토 상태가 유지됩니다.

원문이 수정표·첨부만 제공해 전체 내용을 재구성할 수 없으면 `full_content_checked`를 승인할 수 없습니다. 필요한 첨부가 빠졌다면 `missing_attachments`에 명시합니다. 미래 사업계획 날짜는 자료 공개시점과 다른 개념이므로 그 날짜만으로 폐기하지 않습니다.

검토 이후 `--resume`으로 다시 실행하면 같은 원문과 검증된 검색 구간을 재사용하면서 현재 근거로 승인 여부를 다시 계산합니다. 평가용 ZIP을 만들 때 원문·변환본 해시와 현재 근거를 다시 검사합니다.

## 5종목 → 25종목 → 전체 실행 게이트

프로그램은 5종목의 실제 자료 검증과 검토 보고서가 있어야 25종목을 허용합니다. 전체 실행에는 25종목 검증이 필요합니다. `READY` 외에도 실제 목록 조회를 마치고 공식 출처로 원인을 검토한 정당한 미제출·검토 예외를 보고서에 명시해 인정할 수 있습니다. 기술적 실패나 미실행 종목은 인정하지 않습니다. `config/validation-gates.json`의 형식:

```json
{
  "five": {
    "asof": "2019-09-18",
    "input_sha256": "REPLACE_INPUT_WORKBOOK_SHA256",
    "major_defects_resolved": true,
    "reviewed_by": "REPLACE_REVIEWER",
    "report_path": "config/evidence/five-stock-real-validation.md",
    "report_sha256": "REPLACE_REPORT_SHA256"
  },
  "twenty_five": {
    "asof": "2019-09-18",
    "input_sha256": "REPLACE_INPUT_WORKBOOK_SHA256",
    "major_defects_resolved": true,
    "reviewed_by": "REPLACE_REVIEWER",
    "report_path": "config/evidence/25-stock-real-validation.md",
    "report_sha256": "REPLACE_REPORT_SHA256"
  }
}
```

정당한 예외를 인정하려면 해당 `five` 또는 `twenty_five` 객체에 `accepted_exceptions`를 추가하고 종목코드별로 현재 CSV와 동일한 `status`, `reason`, 공식 출처 확인 여부 `official_sources_checked: true`, 실제 확인한 원인 `documented_cause`를 기록합니다. 이 기록은 수집 상태를 `READY`로 바꾸지 않습니다. 검토 보고서에는 예외와 중대한 구현 결함을 구분해야 합니다. 오류 원인을 조사하지 않고 예외로 승인해서는 안 됩니다.

## Claude Code 독립검수 인계

1. 사용자가 별도로 제공하는 원본 명세서, 전체 소스와 `tests/`를 읽고 `python -m pytest -q tests --junitxml=logs/independent-tests.xml`을 실행합니다. 원본 명세서는 클라우드의 `docs/specification.txt`에 보존했으며 GitHub에는 올리지 않았습니다.
2. Codex 테스트 외에 정정 체인 단절, 부분 원문, 과거 사명, 기업 승계, 누락 페이지, 기존 파일 변조의 독립 반례를 추가합니다.
3. 관리자용 `cache/admin/`, SQLite, 원본 ZIP과 공식 DART 기록을 대조합니다. 이는 평가용 입력과 별도로 다룹니다.
4. 실제 5종목·25종목의 접수번호·법인·회계기간·정정·원문 바이트를 확인합니다. 현재 개발 로그만으로 실자료 시험에 합격했다고 판단하지 않습니다.
5. `PASS / CONDITIONAL PASS / FAIL`, 재현 명령, 발견 결함, 보완 조건을 독립 보고서에 남깁니다. 현재 Claude Code 검수는 실시되지 않았습니다.
