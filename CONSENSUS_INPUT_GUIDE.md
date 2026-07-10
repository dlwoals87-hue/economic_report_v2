# CONSENSUS_INPUT_GUIDE

## 1. expected란 무엇인가

`expected`는 경제지표가 실제로 발표되기 전에 시장이 예상한 값입니다.
BLS 공식 발표값이 아니며, 발표 후 확인되는 실제 CPI 값과 구분해서 기록해야 합니다.

## 2. 네 가지 CPI 예상치

CPI 이벤트에는 아래 네 가지 예상치를 따로 입력합니다.

- `headline_mom`
- `headline_yoy`
- `core_mom`
- `core_yoy`

## 3. 입력 예시

아직 입력 전:

```json
"expected": null
```

입력 완료 예시:

```json
"expected": 0.3
```

`expected` 값 안에는 `%`를 쓰지 않습니다. 단위는 같은 metric 안의 `"unit": "%"`로만 표시합니다.

## 4. 출처 기록

예상치를 하나라도 입력했다면 `consensus_source`에 사람이 확인한 출처 이름을 기록합니다.
출처를 확인하지 못했다면 값을 만들지 말고 `expected: null`을 유지합니다.

## 5. 입력 시간 기록

예상치를 하나라도 입력했다면 `entered_at_utc`를 timezone-aware ISO 8601 형식으로 기록합니다.
예: `2026-06-10T11:00:00Z`

발표 이후 입력한 값을 발표 전 컨센서스로 저장하면 안 됩니다.
따라서 `entered_at_utc`는 `release_datetime_utc`보다 앞서야 합니다.

## 6. 상태값

- `not_entered`: 네 expected가 모두 `null`
- `partial`: 일부 expected만 숫자로 입력
- `complete`: 네 expected가 모두 숫자로 입력

`consensus_status`는 실제 입력 상태와 일치해야 합니다.

## 7. 검증 명령어

```powershell
python scripts/validators/validate_calendar_events.py
```

Codex 번들 Python을 사용할 때:

```powershell
C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe scripts/validators/validate_calendar_events.py
```

## 8. 자주 하는 실수

- `"expected": "0.3%"`처럼 `%`를 값에 직접 넣는 경우
- `"expected": ""`처럼 빈 문자열을 넣는 경우
- `"expected": "약 0.3"`처럼 숫자가 아닌 설명을 섞는 경우
- 예상치를 입력했지만 `consensus_source`를 비워두는 경우
- 예상치를 입력했지만 `entered_at_utc`를 비워두는 경우
- `entered_at_utc`에 timezone 없이 `2026-06-10T11:00:00`처럼 입력하는 경우
- 발표 이후 입력한 값을 사전 예상치처럼 저장하는 경우
