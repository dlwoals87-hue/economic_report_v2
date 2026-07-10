# 실제 경제지표 리포트 메인 페이지 등록 안내서

## 등록 과정

실제 CPI 리포트는 Capture와 Process workflow를 거쳐 다음 순서로 만들어진다.

`as_released.json` → `canonical_release.json` → rule_based 분석 → `docs/reports/{event_id}.html` → `docs/index.html`

마지막 단계는 report HTML과 canonical, 분석 연결이 모두 정상일 때만 실행된다. report가 없으면 `REPORT_NOT_FOUND`로 정상 대기하며 index를 수정하지 않는다.

## sample 리포트와 실제 리포트

기존 sample 링크는 `docs/index.html`에 그대로 남는다. 실제 발표 리포트는 별도 `실제 발표 리포트` 영역에만 등록되며, sample 영역을 삭제하거나 바꾸지 않는다.

## Marker 관리 방식

자동 관리 영역은 다음 marker 사이로 한정한다.

```html
<!-- AUTO_REAL_REPORTS_START -->
<!-- AUTO_REAL_REPORTS_END -->
```

marker가 처음 없을 때에는 `</body>` 직전에 한 번만 삽입한다. 이후에는 marker 바깥의 바이트 내용을 변경하지 않는다. 기존 style과 script 블록, 제목, sample 링크는 그대로 보존한다.

## 최신순과 중복 방지

항목은 `release_datetime_kst` 최신순으로 정렬한다. event ID당 항목은 하나뿐이며, 같은 event ID·링크·기준월·SHA-256 조합으로 다시 실행하면 `INDEX_ALREADY_UP_TO_DATE`로 끝나고 파일 수정 시각도 바꾸지 않는다.

같은 event ID의 링크, 기준월 또는 report SHA-256이 다르면 `INDEX_CONFLICT`다. 이 경우 기존 index와 report를 자동 덮어쓰거나 삭제하지 않는다.

## style과 기존 링크 보호

업데이트 전후 style과 script 블록을 비교한다. 기존 sample href가 하나라도 사라지면 실패한다. 동적 표시값은 모두 HTML escape 처리하며, script, iframe, event handler, javascript URL, 외부 추적 코드, 사용자 PC 절대경로를 새 관리 영역에 넣지 않는다.

## 자동 커밋 경로

Process workflow는 최대 4개만 커밋할 수 있다.

- `data/generated/cpi/*/canonical_release.json`
- `data/analysis/cpi/*/cpi-analysis-v1.json`
- `docs/reports/*.html`
- `docs/index.html`

`docs/index.html`은 실제로 변경된 경우에만 포함된다. 다른 docs 경로는 허용하지 않는다. stage 후에는 `commit_paths`와 staged 목록의 일치, 파일 수, symlink, 삭제 여부, 자격증명 형태를 다시 검사한다.

## 비용과 외부 API

이 과정은 `rule_based` 분석 결과와 로컬 파일만 사용한다. 외부 API 호출은 없고 비용은 무료다. 결과 JSON의 `external_api_called`는 `false`, token usage는 0, `cost_mode`는 `free`여야 한다.

## 수동 확인

실제 report가 생성된 뒤 다음 명령으로 index 등록만 점검할 수 있다.

```powershell
python scripts/automation/update_report_index.py `
  --event-id US_CPI_2026_06 `
  --result-json "$env:TEMP\cpi_index_result.json"
```

현재처럼 발표 전이라 report가 없으면 `REPORT_NOT_FOUND`가 정상이다. 실제 발표일에는 Capture 성공, report 생성, Process workflow 결과의 `docs/index.html` commit 포함 여부를 순서대로 확인한다.
