# 확인한 공식 API 명세

2026-10-21 KST에 HTTPS 인증서 검증을 유지한 읽기 요청으로 확인했습니다. 인증키는 사용하지 않았습니다. 원문 HTML은 `cache/official_guides/`에 보존했습니다.

- [공시검색 list.json](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001): `last_reprt_at=N`이면 정정 포함 제출 보고서 전체, `page_count` 최대 100, 고유번호가 없으면 3개월 제한. 본 프로그램은 고유번호를 사용합니다.
- [공시서류 원본파일 document.xml](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003): ZIP 바이너리 응답.
- [고유번호 corpCode.xml](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019018): ZIP 안의 법인 고유번호·현재 명칭·종목코드.
- `013`은 조회 데이터 없음, `020`은 요청 제한 초과, `800`은 시스템 점검. `020` 제한은 통상 20,000회라고 설명하지만 키별 설정에 따라 다를 수 있어 횟수를 추정해 무시하지 않습니다.

이 가이드 확인으로 과거 원문이 당시 버전과 같다는 사실이나 전체 역사 기간의 제공 범위를 증명한 것은 아닙니다. 실제 API 인증·공식 원문·정정 이력 대조는 별도의 검증입니다.
