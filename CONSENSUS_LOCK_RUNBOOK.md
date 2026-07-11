# CPI 시장 예상치 사전 잠금 안내서

## 예상치의 의미

예상치는 CPI 발표 전 시장이 기대한 네 수치, 즉 headline month-over-month/year-over-year와 core month-over-month/year-over-year를 뜻한다. 네 값은 하나의 신뢰할 수 있는 출처에서 함께 확인해 입력한다. 서로 다른 출처의 숫자를 섞지 않는다.

`data/calendar/events.json`의 대상 event에 네 `expected` 값, `consensus_source`, `entered_at_utc`를 입력한 뒤 `consensus_status`를 `complete`로 설정한다. 실제 숫자는 사용자가 신뢰할 출처를 확인한 뒤에만 입력한다.

## 발표 전 잠금

프로젝트 루트에서 다음 명령을 실행한다.

```powershell
& 'C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts/automation/lock_cpi_consensus.py --event-id US_CPI_2026_06
```

네 값이 완전하고 입력 시각이 발표 전이면 `CONSENSUS_LOCKED`가 반환되며, `data/consensus/cpi/{event_id}/consensus_snapshot.json`에 immutable snapshot이 생성된다. snapshot은 SHA-256으로 검증되고 기존 파일을 덮어쓰지 않는다.

`CONSENSUS_NOT_READY`는 네 값이 모두 비어 있다는 뜻이며 정상적으로 snapshot을 만들지 않는다. `CONSENSUS_PARTIAL`은 일부만 입력된 상태다. 이 경우 출처와 네 수치를 정리한 뒤 다시 잠근다.

## 발표 후 규칙

발표 시각 뒤에는 `CONSENSUS_LOCK_WINDOW_EXPIRED`가 반환된다. 발표 후에 입력한 예상치를 사전 컨센서스로 저장하면 안 된다. 이미 잠긴 동일 입력은 `CONSENSUS_ALREADY_LOCKED`, 값이 달라진 입력은 `CONSENSUS_LOCK_CONFLICT`가 된다. `--force` 같은 우회 옵션은 제공하지 않는다.

## 리포트 영향

canonical은 immutable snapshot만 예상치로 사용한다. calendar에 나중에 숫자를 넣어도 snapshot이 없으면 사용하지 않으며 expected와 surprise는 `null`이다. 컨센서스가 없어도 실제 CPI 리포트는 생성되지만 예상 상회·하회(surprise) 분석은 생성되지 않는다.

이 흐름은 외부 API를 호출하지 않고 비용도 발생하지 않는다. API 키나 토큰을 snapshot에 기록하지 않는다.
