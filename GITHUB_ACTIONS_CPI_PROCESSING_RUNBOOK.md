# CPI 발표 후 무료 리포트 자동 생성 안내서

## 두 workflow의 역할

`Capture CPI Release`는 발표 시점의 원천 응답과 처리 결과를 보존하고 `as_released.json`을 최초 한 번 커밋한다. 수집과 최초값 보존이 이 workflow의 책임이다.

`Process CPI Release`는 이미 저장된 `as_released.json`만 읽어 다음 파생 파일을 만든다.

- `data/generated/cpi/{event_id}/canonical_release.json`
- `data/analysis/cpi/{event_id}/cpi-analysis-v1.json`
- `docs/reports/{event_id}.html`

후처리가 실패해도 Capture가 저장한 `as_released.json`은 수정하거나 삭제하지 않는다.

## workflow_run 동작

Capture workflow가 `main`에서 성공적으로 완료되면 `workflow_run` 트리거가 후처리 workflow를 시작한다. 후처리는 최신 `main`을 다시 checkout하므로 Capture가 방금 push한 최초 발표 파일을 기준으로 실행된다.

Capture 결론이 `success`가 아니면 후처리 job은 실행하지 않는다. 별도의 push, pull request, schedule 트리거는 사용하지 않는다.

## 비용이 없는 이유

분석 공급자는 `rule_based`로 고정한다. 외부 AI API와 BLS API를 호출하지 않고 별도 API 자격증명을 workflow에 전달하지 않는다. 결과의 `external_api_called`는 `false`, 토큰 사용량은 모두 0, `cost_mode`는 `free`여야 한다.

## 자동 선택과 NO_PENDING_EVENT

선택기는 calendar의 CPI 이벤트 중 `as_released.json`이 존재하는 이벤트를 검사한다. 세 파생 파일이 모두 정상인 이벤트는 자동 대상에서 제외한다.

대상이 없으면 `NO_PENDING_EVENT`로 정상 종료한다. 이 상태에서는 파일 생성, staging, commit, push가 없다. 대상이 둘 이상이면 `MULTIPLE_PENDING_EVENTS`로 실패하며 임의로 하나를 선택하지 않는다.

## 부분 상태 복구

- 파생 파일이 전부 없음: canonical, 분석, HTML 순서로 생성하고 `PROCESSED`
- canonical만 있음: canonical을 검증한 뒤 분석과 HTML을 생성하고 `CANONICAL_ONLY_RESUMED`
- canonical과 분석만 있음: 두 파일의 해시 연결을 검증한 뒤 HTML만 생성하고 `REPORT_ONLY_RESUMED`
- 세 파일이 모두 정상: `ALREADY_PROCESSED`, 파일 수정 없음

analysis가 canonical 없이 존재하거나 HTML이 canonical·analysis 없이 존재하면 `INCONSISTENT_DERIVED_STATE`다. 자동 삭제나 재생성으로 덮어맞추지 않는다.

## 무결성 실패 시 동작

처리 순서는 calendar, `as_released` SHA-256, canonical, rule-based 분석, canonical·analysis 연결 해시, HTML, HTML 핵심 숫자 검증 순서다.

기존 파일 내용이나 해시가 예상과 다르면 `INTEGRITY_CHECK_FAILED`로 종료한다. 기존 파생 파일을 덮어쓰거나 삭제하지 않으며 `commit_paths`는 항상 비운다. 앞 단계에서 새 파일이 만들어졌더라도 전체 검증이 끝나지 않으면 커밋하지 않는다.

## 자동 커밋 경로 제한

전체 검증에 성공한 새 파일만 `commit_paths`에 들어간다. 허용되는 경로는 다음 세 유형뿐이며 최대 3개다.

- `data/generated/cpi/*/canonical_release.json`
- `data/analysis/cpi/*/cpi-analysis-v1.json`
- `docs/reports/*.html`

절대경로, `..`, symlink, 삭제 파일, 허용되지 않은 파일, 자격증명 형태가 포함된 파일은 거부한다. workflow는 `git add .`이나 `git add -A`를 사용하지 않는다. 명시적 경로를 stage한 뒤 staged 목록과 `commit_paths`가 정확히 같은지 다시 검사한다.

## 수동 실행

GitHub Actions의 `Process CPI Release`에서 `Run workflow`를 선택한다. `event_id`를 비우면 자동 선택하며, 특정 이벤트만 점검하려면 예를 들어 `US_CPI_2026_06`을 입력한다. `run_tests` 기본값은 `true`다.

로컬에서는 결과 JSON을 임시 경로에 지정한다.

```powershell
python scripts/automation/run_pending_cpi_processing.py `
  --event-id US_CPI_2026_06 `
  --result-json "$env:TEMP\cpi_processing_result.json"
```

## 실제 발표일 확인

1. Capture workflow가 `CAPTURED`로 성공했는지 확인한다.
2. `main`에 `data/releases/cpi/{event_id}/as_released.json`이 커밋됐는지 확인한다.
3. Process workflow의 결과 상태와 `commit_paths`를 확인한다.
4. 성공 후 위 세 파생 파일의 commit을 확인한다.

현재 `US_CPI_2026_06`은 발표 전이므로 정상 결과는 `NO_PENDING_EVENT`이며 파생 파일을 강제로 만들지 않는다.

## docs 인덱스

이번 단계는 이벤트별 HTML까지만 생성한다. `docs/index.html`에는 아직 자동 등록하지 않으며 인덱스 갱신은 후속 단계에서 별도로 다룬다.
