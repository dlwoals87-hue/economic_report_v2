# CPI_DATA_CONTRACT

## 1. 목적

이 문서는 3.1단계 BLS CPI 수집기를 만들기 전에 CPI 데이터의 의미, series ID, expected 입력 방식, 시간대 변환, revision/as-released 보존 규칙을 확정한다.

이번 계약의 핵심은 CPI를 단일 actual 값으로 보지 않는 것이다. CPI 리포트는 최소 네 가지 핵심 지표를 별도로 관리한다.

- `headline_mom`
- `headline_yoy`
- `core_mom`
- `core_yoy`

3.1단계 수집기는 API 응답을 바로 HTML에 넣지 않는다. BLS 원천 지수 값을 수집하고, 계산/검증을 거친 뒤 canonical payload의 `event.headline`, `event.core`, `event.surprise`, `sources`로 넘긴다.

## 2. CPI 네 가지 핵심 지표

| 지표 | 의미 | 계산 기준 | canonical 위치 후보 |
|---|---|---|---|
| `headline_mom` | 전체 CPI 전월비 | 계절조정 headline CPI 지수의 전월 대비 변화율 | `event.headline.mom` |
| `headline_yoy` | 전체 CPI 전년비 | 비계절조정 headline CPI 지수의 전년 동월 대비 변화율 | `event.headline.yoy` |
| `core_mom` | 근원 CPI 전월비 | 계절조정 core CPI 지수의 전월 대비 변화율 | `event.core.mom` |
| `core_yoy` | 근원 CPI 전년비 | 비계절조정 core CPI 지수의 전년 동월 대비 변화율 | `event.core.yoy` |

표시용 리포트의 기존 legacy flat key는 임시 호환 계층이다. canonical에서는 위 네 값을 분리해 저장하고, flat 변환 단계에서 필요한 위치에 매핑한다.

## 3. BLS series ID

3.1단계 CPI 수집기에서 사용할 BLS series ID 후보는 아래로 고정한다.

| 지표 | BLS series ID | 조정 방식 | 용도 |
|---|---|---|---|
| `headline_mom` | `CUSR0000SA0` | Seasonally adjusted | 전체 CPI 전월비 계산 |
| `headline_yoy` | `CUUR0000SA0` | Not seasonally adjusted | 전체 CPI 전년비 계산 |
| `core_mom` | `CUSR0000SA0L1E` | Seasonally adjusted | 근원 CPI 전월비 계산 |
| `core_yoy` | `CUUR0000SA0L1E` | Not seasonally adjusted | 근원 CPI 전년비 계산 |

BLS 운영 구조는 `BLS_API_KEY` 환경변수 사용을 전제로 한다. API 키는 코드, JSON, HTML, 로그에 기록하지 않는다.

## 4. 계산 규칙

전월비는 계절조정 지수로 계산한다.

```text
mom_pct = (current_sa_index / previous_month_sa_index - 1) * 100
```

전년비는 비계절조정 지수로 계산한다.

```text
yoy_pct = (current_nsa_index / same_month_prior_year_nsa_index - 1) * 100
```

계산 규칙:

- `headline_mom`은 `CUSR0000SA0`의 현재월과 직전월 지수로 계산한다.
- `headline_yoy`는 `CUUR0000SA0`의 현재월과 전년 동월 지수로 계산한다.
- `core_mom`은 `CUSR0000SA0L1E`의 현재월과 직전월 지수로 계산한다.
- `core_yoy`는 `CUUR0000SA0L1E`의 현재월과 전년 동월 지수로 계산한다.
- 내부 계산값은 숫자로 보존하고, 표시값은 별도 formatting 단계에서 `%` 문자열로 만든다.
- 반올림 자리수는 BLS 공식 발표표와 대조해 확정한다. 3.1 초기 구현에서는 BLS 발표표 표시값과의 차이가 반올림 오차 범위를 넘으면 실패 처리한다.

## 5. expected 입력 계약

expected는 공식기관 제공값이 아니다. 1차 MVP에서는 `data/calendar/events.json`에서 수동 관리한다.

CPI expected는 반드시 네 지표별로 구분한다.

```json
{
  "indicator_type": "CPI",
  "period": "2026-06",
  "expected": {
    "headline_mom": {"value": "0.2%", "unit": "%"},
    "headline_yoy": {"value": "2.9%", "unit": "%"},
    "core_mom": {"value": "0.2%", "unit": "%"},
    "core_yoy": {"value": "3.1%", "unit": "%"}
  }
}
```

필수 필드:

- `event_id`
- `indicator_type`
- `country`
- `period`
- `release_datetime_utc`
- `release_timezone`
- `display_timezone`
- `expected.headline_mom`
- `expected.headline_yoy`
- `expected.core_mom`
- `expected.core_yoy`
- `source_label`
- `entered_at_utc`

`expected` 자동화는 별도 단계로 분리한다. 3.1단계에서는 수동 입력값과 BLS actual을 결합해 surprise를 계산한다.

## 6. 시간대 변환

release time은 UTC로 저장한다.

시간대 규칙:

- 원 발표시각은 `America/New_York` 기준으로 해석한다.
- 저장 기준은 `release_datetime_utc`다.
- 한국 표시용 시간은 `Asia/Seoul`로 변환한다.
- 변환에는 Python 표준 라이브러리의 `zoneinfo`를 사용한다.
- 고정 UTC offset 사용은 금지한다.
- DST가 있는 기간과 없는 기간 모두 같은 규칙으로 처리한다.

예:

```json
{
  "release_datetime_utc": "2026-07-15T12:30:00Z",
  "release_timezone": "America/New_York",
  "display_timezone": "Asia/Seoul"
}
```

## 7. revision 및 as-released 보존

CPI는 발표 당시 값과 이후 조회 시점의 최신값을 분리한다.

필수 필드:

- `actual_as_released`: 발표 당시 저장한 계산 결과
- `actual_current`: 현재 재조회 기준 계산 결과
- `retrieved_at_utc`: API 응답을 가져온 UTC 시각
- `release_vintage`: 발표 vintage 식별자. 예: `2026-07-cpi`
- `is_revised`: `actual_as_released`와 `actual_current`가 다르면 `true`

raw API 응답 보존 규칙:

- 발표 당시 raw API 응답은 나중에 덮어쓰지 않는다.
- 같은 release vintage를 재조회하면 기존 파일을 수정하지 않고 새 retrieval record를 만든다.
- raw 저장 경로는 3.1 구현 시 확정하되, `release_vintage`와 `retrieved_at_utc`를 포함해야 한다.
- raw 응답에는 API 키가 포함되지 않도록 저장 전 URL/query string을 마스킹한다.

## 8. 검증 규칙

3.1단계 CPI 수집기는 계산 결과를 BLS 공식 발표표와 대조하는 검증 규칙을 둔다.

검증 항목:

- 네 series ID가 계약과 일치하는지 확인한다.
- 전월비는 계절조정 지수(`CUSR...`)로 계산했는지 확인한다.
- 전년비는 비계절조정 지수(`CUUR...`)로 계산했는지 확인한다.
- 현재월, 직전월, 전년 동월 period가 올바른지 확인한다.
- 계산 결과와 BLS 공식 발표표의 표시값을 대조한다.
- 반올림 오차 범위를 넘는 불일치는 실패 처리하고 수동 검토 대상으로 남긴다.
- `expected` 네 지표가 모두 존재하는지 확인한다.
- `release_datetime_utc`가 존재하고 고정 UTC offset 없이 변환 가능한지 확인한다.
- `actual_as_released`, `actual_current`, `retrieved_at_utc`, `release_vintage`, `is_revised`가 존재하는지 확인한다.

## 9. 3.1단계 입력/출력 계약

입력:

- `BLS_API_KEY` 환경변수
- `data/calendar/events.json`
- CPI 대상 event의 `event_id`
- CPI 대상 `period`
- BLS series ID 4개

출력 후보:

- CPI actual 계산 결과 4개
- CPI previous 계산 기준값
- expected 대비 surprise 4개
- BLS source metadata
- `actual_as_released`
- `actual_current`
- `retrieved_at_utc`
- `release_vintage`
- `is_revised`
- 발표 당시 raw API 응답 보존 record

3.1 구현 범위 밖:

- expected 자동 수집
- intraday market data 수집
- OpenAI/Claude 해석문 생성
- HTML/CSS/template 변경
- GitHub Actions 자동화
