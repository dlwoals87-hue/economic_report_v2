# CPI 실제 발표일 운영 안내서

## 발표 전 확인

- GitHub Actions와 `Capture CPI Release`, `Process CPI Release` workflow가 활성화되어 있는지 확인한다.
- Workflow permissions는 `contents: write`가 필요하며, calendar에는 대상 event와 예상치 상태가 있어야 한다.
- Process workflow는 Secret 없이 `rule_based`로 실행되며 외부 API를 사용하지 않는다. 비용은 0원이다.

진단은 프로젝트 루트에서 Codex 번들 Python으로 실행한다.

```powershell
& 'C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts/diagnostics/check_cpi_release_readiness.py --event-id US_CPI_2026_06
```

성공 출력은 `READINESS_PASS`로 시작한다. calendar, 두 workflow, 무료 기본 provider, 오프라인 전체 흐름과 운영 파일 무변경을 함께 확인한다.

## 발표 직전 확인

- Capture workflow의 최근 실행 상태와 `main` 브랜치를 확인한다.
- schedule이 활성화되어 있고 calendar의 release 시각과 대상월이 맞는지 확인한다.
- 발표 전 상태에서는 `WAITING_FOR_RELEASE`가 정상이다.

## 발표 후 정상 흐름

`Capture CPI Release`가 `CAPTURED`가 되면 `Process CPI Release`가 자동으로 이어진다. 후처리는 canonical, rule_based analysis, HTML, docs/index 순으로 완료되고 `PROCESSED_AND_INDEXED`가 정상 상태다. 이후 Pages 배포에서 최신 실제 리포트 링크를 확인한다.

## 정상 상태별 의미

- `WAITING_FOR_RELEASE`: 발표 시각 전이므로 수집하지 않는다.
- `DATA_NOT_AVAILABLE_YET`: 발표 시각 후지만 BLS에 대상월이 아직 없다.
- `CAPTURED`: 최초 발표값을 immutable as_released로 저장했다.
- `ALREADY_CAPTURED`: 이미 저장된 발표값을 다시 수집하지 않았다.
- `NO_PENDING_EVENT`: 처리할 captured event가 없다.
- `PROCESSED_AND_INDEXED`: canonical, 분석, HTML, index 등록이 완료됐다.
- `INDEX_ALREADY_UP_TO_DATE`: report는 이미 있고 index 등록도 완료됐다.

## 오류 시 금지 행동

`READINESS_FAIL`이면 as_released를 수동 수정하거나 기존 파일을 삭제하거나 실제값을 직접 덮어쓰지 않는다. force push와 broad `git add`도 사용하지 않는다. 실패 항목을 확인해 정상 변경 절차로 고친 뒤 같은 진단을 다시 실행한다.

API 키, PAT, 외부 Secret을 추가해 해결하지 않는다. release flow는 외부 provider 없이 무료 `rule_based`를 기본으로 유지한다.

## 수동 재실행 방법

GitHub Actions에서 `Capture CPI Release`를 수동 실행한 뒤 정상적으로 `CAPTURED`인지 확인한다. 성공 capture가 `main`에서 끝나면 `Process CPI Release`가 자동 실행된다. 후처리가 필요할 때는 해당 workflow를 Actions UI에서 다시 실행하되 immutable artifact를 수동 변경하지 않는다.

## 최종 확인

- `docs/index.html`에 최신 실제 리포트 링크가 있는지 확인한다.
- report의 핵심 숫자와 기준월이 canonical과 일치하는지 확인한다.
- 결과 metadata가 `rule_based`, 외부 API 미사용, 비용 0원인지 확인한다.
- 재실행은 `ALREADY_CAPTURED`, `ALREADY_PROCESSED` 또는 `INDEX_ALREADY_UP_TO_DATE`가 되며 기존 artifact를 바꾸지 않아야 한다.
