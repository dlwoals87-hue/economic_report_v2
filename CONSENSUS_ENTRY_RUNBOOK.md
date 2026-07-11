# CPI 시장 예상치 안전 입력 안내서

## 입력 원칙

CPI 예상치는 headline/core와 month-over-month/year-over-year의 네 값으로 구성된다. 네 숫자는 반드시 한 출처의 같은 시점 데이터로 확인하고, 출처별 숫자를 섞지 않는다. 실제 숫자는 신뢰할 출처를 확인한 사람이 입력한다.

## Preview

먼저 파일을 바꾸지 않는 preview를 실행한다.

```powershell
& 'C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts/automation/set_cpi_consensus.py --event-id US_CPI_2026_06 --headline-mom <값> --headline-yoy <값> --core-mom <값> --core-yoy <값> --source "<출처 이름>" --preview
```

`CONSENSUS_PREVIEW`에서 KST 발표 시각, 입력값, 출처와 경고를 확인한다. `%`, 쉼표, 범위를 벗어난 값, URL이나 인증정보는 입력할 수 없다.

## Apply And Lock

검토한 동일 값으로 별도의 apply를 실행한다.

```powershell
& 'C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts/automation/set_cpi_consensus.py --event-id US_CPI_2026_06 --headline-mom <값> --headline-yoy <값> --core-mom <값> --core-yoy <값> --source "<출처 이름>" --apply
```

apply 뒤 calendar를 검증하고 immutable snapshot을 별도로 잠근다.

```powershell
& 'C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts/validators/validate_calendar_events.py
& 'C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts/automation/lock_cpi_consensus.py --event-id US_CPI_2026_06
& 'C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts/diagnostics/check_cpi_release_readiness.py --event-id US_CPI_2026_06
```

발표 이후에는 입력할 수 없고, snapshot이 생성된 뒤에는 값 수정이 금지된다. 이 도구는 snapshot을 자동 생성하지 않는다. 외부 API 호출과 비용은 없다.
