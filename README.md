# PIT DART Collector

2019년 당시 공개된 자료만 사용하는 STEP 1 수집기 개발판입니다. 투자 점수·탈락 판정·주가 수집·STEP 3은 구현 범위에 포함하지 않습니다. 원본 명세서·엑셀·API 키·실행 기록은 GitHub에 올리지 않습니다.

**현재 상태:** Python 프로그램과 자동 테스트를 작성했습니다. 제공된 엑셀 390종목을 순서·코드 손실 없이 읽는 준비 단계는 실행했습니다. 실제 OpenDART 원문 수집, Windows 실행, 5종목/25종목 공식 기록 대조, Claude Code 독립검수는 아직 완료하지 않았습니다. 이 버전은 개발·검수용입니다.

## Windows에서 시작하기

GitHub에서 받은 ZIP은 먼저 압축을 풉니다. **PC의 Codex로 이어서 작업할 경우 이 프로젝트 폴더를 열고 `docs/CODEX_HANDOFF.md`를 읽고 작업을 이어가라고 요청하세요.** 설치·테스트·첫 5종목 실행은 로컬 에이전트가 진행할 수 있습니다. 원본 엑셀은 저장소에 포함하지 않았으므로 PC에 있는 파일을 `input/universe.xlsx`로 복사해야 합니다. API 키는 채팅으로 보내지 않습니다.

클라우드의 OpenDART 접속 중계 오류 때문에 PC에서 시험을 이어갈 경우 **`run_pc_5_stocks.bat` 하나를 실행**하면 됩니다. 의존성 설치 → 자동 테스트 → 필요한 경우 가려진 키 입력 → 원래 순서의 5종목 수집을 진행합니다. 기존 PC 환경변수가 있으면 키를 다시 묻지 않습니다. 새로 입력한 키는 실행 중인 프로세스의 환경변수에만 넣고 파일에는 저장하지 않습니다. 끝나면 `logs/PC_5_stock_diagnostics.zip`을 확인하세요. 자세한 안내는 [PC 시험 안내](docs/PC_TEST.md)에 있습니다.

직접 실행할 때는 원본 엑셀을 준비하고 그 폴더에서 다음 순서로 실행합니다. Python 3.11 이상이 필요합니다.

1. `install.bat`: 가상환경과 패키지 설치.
2. `prepare_input.bat`: 엑셀 검증·미래정보를 제거한 코드 목록 생성. API 요청 없음.
3. `run_tests.bat`: 가짜 API로 오류 처리·PIT 통제 논리 검사. 실자료 검증과 다릅니다.
4. [API 키 설정 안내](docs/WINDOWS_KEY.md)에 따라 **본인의 PC에만** `DART_API_KEY`를 설정.
5. `run_5_stocks.bat`: 처음 5종목으로 실제 API 시도. 390종목 전체를 먼저 실행하지 않습니다.

더블클릭한 창이 바로 닫히면 폴더에서 PowerShell을 열고 `cmd /c run_5_stocks.bat`로 실행해 메시지를 확인하세요. 키 값을 명령행 인자나 채팅에 붙여 넣지 마세요. VS Code에서는 이 폴더의 `.venv\Scripts\python.exe`를 인터프리터로 선택합니다.

이 GitHub 저장소와 GitHub에서 내려받는 ZIP에는 원본 입력 엑셀이 없습니다. 이전 클라우드에서 만든 개발용 ZIP은 원본 입력 엑셀을 포함할 수 있습니다. **개발용 ZIP과 `input/`, `cache/`, `config/`는 평가용으로 전달하지 않습니다.** 2026년 관리자 자료가 들어 있기 때문입니다. Claude 평가용으로는 프로그램이 별도로 생성한 자료팩만 사용합니다.

## 실행 명령

작업 디렉터리는 저장소 최상위 폴더입니다. Windows에서 아래 `python` 대신 `.venv\Scripts\python.exe`, 이 클라우드에서는 `/workspace/.venvs/dart/bin/python`을 사용합니다.

```text
python -m pit_dart --input input/universe.xlsx --asof 2019-09-18 --expected-count 390 --prepare
python -m pit_dart --input input/universe.xlsx --asof 2019-09-18 --test --resume
python -m pit_dart --input input/universe.xlsx --asof 2019-09-18 --verify
python -m pit_dart --input input/universe.xlsx --asof 2019-09-18 --test --package-only
```

`--test`는 원래 순서의 최대 5종목입니다. `--stock-codes 000140,000390,...`로 시험 대상을 지정해도 원래 엑셀 순서는 유지합니다. 코드·기준일을 바꾸면 다른 연도로 적용할 수 있습니다. 입력 파일이나 검색 시작일이 기존 결과와 다르면 별도의 `--workspace`를 사용해야 합니다.

25종목은 `--batch-size 25 --batch-id 1`, 다음 배치는 `--batch-id 2`로 선택합니다. 전체 처리는 `--all --batch-size 25`입니다. 5종목 공식 검증 결과와 검수 보고서를 등록하기 전에는 25종목 실행을, 25종목 공식 검증 전에는 전체 실행을 차단합니다. 게이트 등록은 [검수 안내](docs/REVIEW.md)를 따릅니다. 현재 이 게이트들은 통과하지 않았습니다.

평가용 ZIP은 `--package`로 실행 뒤 생성하거나 `--package-only`로 기존 배치를 포장합니다. `--split-size 12`를 주면 25종목 배치는 12종목·13종목 두 ZIP으로 나눕니다. 배치별 평가용 목록과 파일만 포함하며 관리자 캐시를 재귀적으로 압축하지 않습니다.

## 자료를 승인하는 기준

다운로드한 ZIP은 먼저 `cache/raw/`에 격리합니다. 현재 `corpCode.xml`의 종목코드 매핑은 **후보 탐색**에 사용하며 과거 법인 동일성의 증거로 승인하지 않습니다. 후보가 복수면 임의 선택하지 않습니다. 자동 매칭이 실패하면 당시 검색명 등은 관리자 후보 목록에만 기록하고 DART/KRX/공식 기업변경 자료를 이용한 검토를 요구합니다. 웹 검색을 자동으로 완결하는 기능은 없습니다.

공시 목록은 1999-01-01부터 정보마감일까지 연속된 연도별 구간을 검색합니다. `last_reprt_at=N`, 페이지당 100건으로 전체 페이지·건수·중복·경계·법인번호를 검사합니다. 공식 가이드에서 API의 정확한 최초 제공일을 독립 확인하지 못했기 때문에 검색 시작 이전 기간은 미검증으로 명시합니다. 최초 제공일 확인 근거 없이 전체 역사 범위를 확보했다고 승인하지 않습니다. 임의의 최근 1년·3년 제한은 허용하지 않습니다.

제목의 보고기간은 **다운로드 후보 선택**에 사용합니다. 사업보고서는 가장 최근 회계기간, 반기·분기는 둘 중 가장 최근 회계기간을 고릅니다. 현재의 정정·철회 비고(`rm`)는 평가용으로 내보내지 않습니다. 같은 기간 정정 연결은 독립 접수번호와 공식 기록 근거로 확인해야 합니다.

기업 동일성, 정확한 원문 바이트의 SHA256, 접수번호·보고기간·정정 연결·당시 유효한 버전과 내용·첨부자료를 공식 기록과 대조한 근거가 있어야 평가용 `raw/`와 `readable/`에 복사합니다. API만으로 과거 버전을 입증할 수 없으면 `PIT_REVIEW_REQUIRED`로 남습니다. 자동으로 역사적 동일성을 보장한다고 주장하지 않습니다. 독립 검수자는 [증거 형식](docs/REVIEW.md)에 따라 검토 결과를 기록할 수 있습니다. 사용자가 지금 직접 작성해야 하는 파일은 아닙니다.

`READY`는 필요한 검증을 모두 충족한 종목에만 부여합니다. `REVIEW_REQUIRED`, `MISSING`, `FAILED`, `NOT_RUN`은 서로 다릅니다. 검색 범위 안에 보고서가 없다는 결과는 `NOT_FILED_IN_SEARCHED_RANGE`이고, 전체 제공기간·기업 동일성까지 확인한 경우에만 `NOT_FILED_ASOF`가 됩니다. API 오류는 `FETCH_FAILED`입니다. 기업 식별 실패는 투자 탈락이 아닙니다.

현재 문서 원본이 정정표만 포함하고 전체 보고서 내용을 제공하지 않으면 `full_content_checked`를 승인하면 안 됩니다. 자동으로 원본과 부분 정정을 합성하는 기능은 없으며 이 경우 검토 필요 상태가 유지됩니다. 필요한 공식 첨부가 없으면 `missing_attachments`에 기록합니다.

## 결과와 재실행

```text
input/universe.xlsx                  원본 엑셀(관리자용, Git 제외)
config/reviews.json                   공식 기록 검토 근거(관리자용)
config/evidence/                      검토 근거 파일(관리자용)
cache/state.sqlite3                  구간·다운로드·진행 상태
cache/raw/                           검토 전 원본 ZIP
cache/admin/                         현재 법인 후보·원본 API 목록·범위 검사
output/2019-09-18/coverage.csv         390종목 전체 상태(미실행도 포함)
output/2019-09-18/universe_asof.csv    코드·순번 중심 입력 목록
output/2019-09-18/batch_001_005/       시험 배치
  raw/                               승인된 원본만
  readable/                          승인된 원문의 읽기용 HTML
  universe_asof.csv
  manifest.csv
  disclosure_index.csv
  missing.csv
  identity_review.csv
  coverage.csv
  collection_report.md
logs/                                자동 테스트·실행·파일 재검증 기록
```

미확인 공시유형도 목록에서 버리지 않고 `other_or_nonperiodic`으로 남깁니다. 수시공시 원문은 대량 다운로드하지 않습니다. 각 배치 보고서에서 격리된 원문 수와 평가용 승인 원문 수를 따로 확인합니다.

`--resume`은 검증된 검색 구간을 재사용하고 원문은 매번 해시와 ZIP/XML을 재검사합니다. 손상된 파일은 증거로 보존하고 다시 내려받습니다. `--verify`는 API 요청 없이 기존 파일을 재검사하며 손상·누락을 발견하면 승인 상태도 취소합니다. 검토 설정·근거가 달라지면 이전 승인으로 ZIP을 만들지 못합니다.

요청은 동시 실행하지 않고 1초 이상 간격을 둡니다. 네트워크/서버 오류는 제한적으로 재시도하며 일일 제한 `020`이나 인증 오류가 발생하면 다음 요청·배치를 시작하지 않습니다. 다음에 `--resume`으로 재시도합니다. TLS·패키지 검증은 끄지 않습니다.

종료 코드 0은 명령이 수행됐다는 뜻입니다. 수집 완료 여부는 CSV 상태와 보고서로 확인합니다. 종료 코드 2는 입력·접속·인증·무결성 등의 오류이며 130은 사용자가 중단한 경우입니다. 파일 0건으로 검증 명령이 끝나도 수집을 검증했다고 해석하지 않습니다.

## 검수와 남은 작업

```text
python -m pytest -q tests --junitxml=logs/tests.xml
```

테스트 데이터·법인·공식 기록 모사 파일은 모두 가짜입니다. 실제 5종목/25종목 결과를 대신하지 않습니다. 남은 실제 자료 검증, Windows 실행 확인, 공식 역사적 신원·정정 증거 확보, Claude Code 독립검수의 현황은 [개발 상태](docs/STATUS.md)에 기록합니다.
