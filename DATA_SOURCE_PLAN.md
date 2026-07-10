# DATA_SOURCE_PLAN

## 1. 결론

- 3.1단계의 첫 구현은 `BLS CPI actual/previous 수집`이 가장 안전하다. 현재 canonical 구조의 `event.headline`, `event.core`, `event.sub_metrics[]`, `event.surprise`와 가장 가깝다. 운영 구조는 `BLS_API_KEY` 환경변수 사용을 전제로 한다.
- `actual`과 `previous`는 공식 통계 출처에서 수집한다. `expected/consensus`는 공식기관이 제공하는 값이 아니므로 1차 MVP에서는 수동 `calendar JSON`으로 관리한다.
- FRED는 일별 거시 배경 데이터와 금리/유동성 시계열용으로 분류한다. 발표 직후 또는 +1시간 시장 반응은 FRED만으로 처리하지 않고, 별도 intraday market data provider가 필요하다고 본다.
- FOMC와 ISM은 숫자 API보다 문서/텍스트 해석의 비중이 크다. 3.1 첫 구현 대상이 아니라, CPI/PPI/NFP 수집기 패턴을 먼저 만든 뒤 연결한다.

참고한 공식 문서:
- BLS Public Data API: https://www.bls.gov/developers/
- BEA Data API: https://apps.bea.gov/api/signup/
- FRED API: https://fred.stlouisfed.org/docs/api/fred/
- FRED API Key: https://fred.stlouisfed.org/docs/api/api_key.html
- FRED series observations: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- Federal Reserve FOMC calendars: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- U.S. Census Economic Indicators API: https://www.census.gov/data/developers/data-sets/economic-indicators.html
- ISM PMI Reports: https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/
- CoinGecko API docs: https://docs.coingecko.com/

## 2. 지원 대상 지표

| indicator_type | 표시 이름 | 1차 카테고리 | 현재 canonical 핵심 구조 |
|---|---|---|---|
| `CPI` | 미국 소비자물가지수 | inflation | `event.headline`, `event.core`, `event.sub_metrics[]` |
| `PPI` | 미국 생산자물가지수 | inflation | `event.headline`, `event.core`, `event.sub_metrics[]` |
| `PCE` | 미국 개인소비지출 물가지수 | inflation | `event.headline`, `event.core`, `event.sub_metrics[]` |
| `NFP` | 미국 비농업고용 | labor | `event.headline`, optional `event.core`, `event.sub_metrics[]` |
| `UNEMPLOYMENT_RATE` | 미국 실업률 | labor | `event.headline`, `event.sub_metrics[]` |
| `AVERAGE_HOURLY_EARNINGS` | 미국 평균시급 | labor | `event.headline`, `event.sub_metrics[]` |
| `RETAIL_SALES` | 미국 소매판매 | growth | `event.headline`, `event.core`, `event.sub_metrics[]` |
| `ISM_MANUFACTURING` | 미국 ISM 제조업 PMI | business_survey | `event.headline`, `event.sub_metrics[]` |
| `ISM_SERVICES` | 미국 ISM 서비스업 PMI | business_survey | `event.headline`, `event.sub_metrics[]` |
| `FOMC_RATE_DECISION` | 미국 FOMC 금리결정 | monetary_policy | `event.headline`, optional `event.core`, `event.sub_metrics[]` |

3.0B 보정: CPI는 단일 actual이 아니라 `headline_mom`, `headline_yoy`, `core_mom`, `core_yoy` 네 지표를 별도로 관리한다.

## 3. 지표별 데이터 출처 표

| indicator_type | actual 출처 | previous 출처 | expected 출처 | 필요한 핵심 필드 | API 키 필요 여부 | 1차 구현 난이도 |
|---|---|---|---|---|---|---|
| `CPI` | BLS Public Data API, CPI series | 동일 BLS series의 직전 관측치 | `data/calendar/events.json` 수동 입력 | `headline_mom`, `headline_yoy`, `core_mom`, `core_yoy`, release period, release vintage | 운영: `BLS_API_KEY` 환경변수 사용 전제 | 낮음 |
| `PPI` | BLS Public Data API, PPI series | 동일 BLS series의 직전 관측치 | 수동 calendar JSON | headline PPI, core PPI, final demand goods/services, trade services, transportation, energy | 운영: `BLS_API_KEY` 환경변수 사용 전제 | 중간 |
| `PCE` | BEA Data API, NIPA / Personal Income and Outlays 관련 표 | 동일 BEA series의 직전 관측치 | 수동 calendar JSON | headline PCE price index, core PCE, goods, services, housing/healthcare 등 | 필요로 간주. BEA API 등록/UserID 관리 | 중간 |
| `NFP` | BLS Public Data API, CES employment series | 동일 BLS series의 직전 관측치 및 revision | 수동 calendar JSON | nonfarm payrolls, private payrolls, revision, unemployment_rate, average_hourly_earnings | 운영: `BLS_API_KEY` 환경변수 사용 전제 | 중간 |
| `UNEMPLOYMENT_RATE` | BLS Public Data API, CPS unemployment series | 동일 BLS series의 직전 관측치 | 수동 calendar JSON | unemployment rate, participation rate, U-6, employment-population ratio | 운영: `BLS_API_KEY` 환경변수 사용 전제 | 낮음 |
| `AVERAGE_HOURLY_EARNINGS` | BLS Public Data API, CES earnings series | 동일 BLS series의 직전 관측치 | 수동 calendar JSON | average hourly earnings MoM/YoY, weekly hours | 운영: `BLS_API_KEY` 환경변수 사용 전제 | 낮음 |
| `RETAIL_SALES` | U.S. Census Economic Indicators API | 동일 Census series의 직전 관측치 | 수동 calendar JSON | headline retail sales, ex-auto, control group, gasoline, restaurants | Census API 키 필수 | 중간 |
| `ISM_MANUFACTURING` | ISM Manufacturing PMI report page | 직전 ISM report | 수동 calendar JSON | headline PMI, new orders, prices paid, employment, supplier deliveries | 공식 공개 API 확인 필요. 페이지/수동은 키 없음 | 높음 |
| `ISM_SERVICES` | ISM Services PMI report page | 직전 ISM report | 수동 calendar JSON | headline PMI, business activity, new orders, prices paid, employment | 공식 공개 API 확인 필요. 페이지/수동은 키 없음 | 높음 |
| `FOMC_RATE_DECISION` | Federal Reserve FOMC statement, implementation note, projection materials | 직전 FOMC statement/implementation note | 수동 calendar JSON | target rate range, decision, vote, statement tone, dot plot, press conference tone | 키 없음 | 중간~높음 |

## 4. actual / previous / expected 처리 원칙

- `actual`은 공식 출처에서 수집한다.
  - CPI/PPI/NFP/실업률/평균시급: BLS 우선.
  - PCE: BEA 우선.
  - 소매판매: U.S. Census 우선.
  - ISM: ISM 공식 report 우선.
  - FOMC: Federal Reserve 공식 FOMC 페이지 우선.
- `previous`는 같은 공식 시계열의 직전 관측치를 사용한다.
  - revision이 있는 지표는 `previous_initial`, `previous_revised`, `revision_delta`를 분리하는 구조가 필요하다.
  - NFP는 revision 영향이 크므로 3.1 이후 노동지표 수집 단계에서 별도 필드로 분리한다.
- `expected`는 공식기관 제공값이 아니다.
  - 1차 MVP에서는 `data/calendar/events.json`에서 수동 관리한다.
  - CPI expected는 `headline_mom`, `headline_yoy`, `core_mom`, `core_yoy` 네 지표별로 구분한다.
  - 필수 필드 후보: `indicator_type`, `period`, `release_datetime_utc`, `release_timezone`, `display_timezone`, `expected`, `source_label`, `source_url`, `entered_at_utc`.
  - expected 자동화는 별도 단계로 분리한다. Bloomberg/Reuters/FactSet 같은 컨센서스는 라이선스 이슈가 있으므로 무료 MVP 범위에 넣지 않는다.
- surprise 계산은 수집기가 아니라 canonical 조립 단계에서 처리한다.
  - 숫자 지표: `actual - expected`, 단위 `%p`, `K`, index point, bp를 보존.
  - 방향 판단: `indicator_profiles.json`의 `category`, `direction_good_when`, 지표별 profile로 판정.
  - z-score/백분위는 과거분포 구축 이후 단계로 분리한다.
- CPI 계산 규칙은 `CPI_DATA_CONTRACT.md`를 따른다.
  - 전월비는 계절조정 지수(`CUSR...`)로 계산한다.
  - 전년비는 비계절조정 지수(`CUUR...`)로 계산한다.
  - 계산 결과는 BLS 공식 발표표와 대조한다.
  - `actual_as_released`와 `actual_current`를 분리하고 `retrieved_at_utc`, `release_vintage`, `is_revised`를 둔다.
  - 발표 당시 raw API 응답은 나중에 덮어쓰지 않는다.
  - release time은 UTC로 저장하고 `America/New_York`에서 `Asia/Seoul`로 `zoneinfo` 변환한다. 고정 UTC offset은 금지한다.

## 5. 시장 반응 데이터 소스

| 데이터 | 우선 출처 | 대체 출처 | API 키 필요 여부 | 주의사항 |
|---|---|---|---|---|
| S&P500 | FRED `SP500` | Stooq, Yahoo Finance, 수동 입력 | FRED는 필요 | FRED는 일별 거시 배경 데이터용. 발표 직후/+1시간 반응은 별도 intraday provider 필요 |
| Nasdaq | FRED `NASDAQCOM` 또는 Nasdaq Composite 관련 series | Stooq, Yahoo Finance, 수동 입력 | FRED는 필요 | FRED는 일별 거시 배경 데이터용. Nasdaq Composite/Nasdaq 100 중 기준을 고정해야 함 |
| 미국 2년물 금리 | FRED `DGS2` | Treasury Daily Treasury Rates, 수동 입력 | FRED는 필요 | 일별 거시 배경 데이터용. 발표 직후 bp 변화는 별도 intraday provider 필요 |
| 미국 10년물 금리 | FRED `DGS10` | Treasury Daily Treasury Rates, 수동 입력 | FRED는 필요 | 일별 거시 배경 데이터용. `DGS10 - DGS2` 같은 curve 계산은 후처리 |
| 달러 | FRED trade-weighted dollar index 후보 | ICE DXY 데이터, 수동 입력 | FRED는 필요. ICE DXY는 라이선스 확인 필요 | DXY와 trade-weighted dollar는 다른 지표이므로 이름을 명확히 분리 |
| 금 | FRED gold price series 후보 | LBMA, Stooq, 수동 입력 | FRED는 필요 | 장중 반응보다 일별 기준으로 먼저 구현 |
| 비트코인 | CoinGecko Simple Price / market chart | Coinbase, Binance, 수동 입력 | 초기 keyless 테스트 가능, 운영은 키 사용 권장 | 24시간 거래라 발표시각 기준 window 계산이 중요 |
| 금리 인하 확률 또는 금리 기대 | CME FedWatch 페이지 수동/후보, FRED Fed Funds futures 관련 후보 | 수동 calendar JSON | CME 공식 공개 API 확인 필요. FRED는 필요 | 1차 MVP에서는 expected와 마찬가지로 수동 입력 권장 |
| 시장 폭 | FRED 후보 제한적, 거래소/벤더 필요 | 수동 입력 | 공급원별 상이 | 상승종목비율, 52주 신고/신저는 공식 무료 API 난이도 높음 |
| 유동성/RRP/TGA | FRED 또는 Federal Reserve/H.4.1 계열 | 수동 입력 | FRED는 필요 | 발표 당일 시장반응보다는 배경 데이터로 취급 |

## 6. API 키와 보안 원칙

- API 키는 코드, JSON, HTML, 로그, 커밋 메시지에 쓰지 않는다.
- 로컬 실행은 환경변수만 사용한다.
  - 후보 이름: `BLS_API_KEY`, `BEA_API_KEY`, `FRED_API_KEY`, `COINGECKO_API_KEY`, `CENSUS_API_KEY`.
  - BLS 운영 구조는 `BLS_API_KEY`를 전제로 한다.
  - Census는 API 키 필수로 취급한다.
  - CoinGecko는 초기 keyless 테스트가 가능하더라도 운영은 키 사용을 권장한다.
- GitHub Actions 단계에서는 GitHub Secrets만 사용한다.
- 이번 단계에서는 키를 만들거나 입력하지 않는다.
- 문서와 샘플 JSON에는 실제 키, 실제 토큰, 개인 계정 정보, 유료 데이터 출처 인증정보를 넣지 않는다.
- API 응답 원문을 저장할 경우에도 URL query string에 키가 포함되지 않도록 마스킹한다.

## 7. 3.1단계 추천 구현 순서

1. BLS CPI actual/previous 수집
   - 현재 샘플 구조와 가장 가깝고, CPI 네 지표(`headline_mom`, `headline_yoy`, `core_mom`, `core_yoy`) 매핑 검증에 좋다.
   - 운영 구조는 `BLS_API_KEY` 환경변수 사용을 전제로 한다.
2. BLS PPI actual/previous 수집
   - CPI와 같은 BLS 수집기 패턴을 재사용하면서 inflation 계열 확장성을 검증한다.
3. BLS NFP/실업률/평균시급 수집
   - 같은 BLS API를 쓰되 CES/CPS/revision 차이를 다룬다.
4. FRED 금리 데이터 수집
   - `DGS2`, `DGS10` 중심으로 일별 거시 배경 데이터의 첫 축을 만든다. 발표 직후/+1시간 시장 반응은 별도 intraday provider 단계로 분리한다.
5. BEA PCE 수집
   - Fed 선호 물가 지표지만 BEA API와 표 구조 확인이 필요해 CPI/PPI 이후가 좋다.
6. FOMC 성명서 링크/텍스트 수집
   - Federal Reserve 공식 페이지의 statement, implementation note, projection materials 링크를 canonical `sources`와 `event.sub_metrics[]`에 연결한다.
7. expected 수동 calendar JSON 구조 추가
   - actual 수집기와 별개로 consensus 수동 입력 구조를 먼저 안정화한다.

## 8. 3.1단계 전 확인 사항

| 확인 항목 | 필요한 결정 |
|---|---|
| BLS series_id 후보 | CPI는 `headline_mom=CUSR0000SA0`, `headline_yoy=CUUR0000SA0`, `core_mom=CUSR0000SA0L1E`, `core_yoy=CUUR0000SA0L1E`를 3.1 후보로 둔다. PPI/NFP 등은 별도 확정 |
| FRED series_id 후보 | `DGS2`, `DGS10`, `SP500`, `NASDAQCOM`, dollar index, gold, RRP/TGA/liquidity 후보 확정 |
| BEA API 키 필요 여부 | BEA API UserID/등록 절차와 무료 사용 조건 확인 |
| expected 수동 입력 파일 구조 | `data/calendar/events.json`을 사용한다. CPI expected는 네 지표별로 구분한다. 예시는 `data/calendar/events.example.json` 참고 |
| 발표 시각 KST 변환 기준 | release time은 UTC로 저장한다. 미국 Eastern Time 발표시각은 `America/New_York` 기준으로 해석하고 `zoneinfo`로 `Asia/Seoul` 변환한다. 고정 UTC offset은 금지 |
| frequency / unit 표준 | YoY, MoM, index, K, bp, tone 같은 단위를 canonical에서 그대로 보존 |
| previous/revision 처리 | `actual_as_released`와 `actual_current`를 분리하고 `retrieved_at_utc`, `release_vintage`, `is_revised`를 둔다. 발표 당시 raw API 응답은 덮어쓰지 않는다 |
| source attribution | `sources[]`에 official URL, retrieved_at, series_id, table_id를 남기는 규칙 |
| API 호출 실패 시 fallback | 1차는 실패 시 수동 sample 유지, report build는 중단하지 않는 정책 검토 |

## 9. 이번 단계에서 하지 않는 것

- 실제 API 호출을 하지 않는다.
- API 키를 만들거나 입력하지 않는다.
- 코드, JSON, HTML, 템플릿을 수정하지 않는다.
- `scripts/build_report.py`와 `scripts/standard_to_flat_payload.py`를 수정하지 않는다.
- GitHub Actions, DB, 서버, 외부 라이브러리를 추가하지 않는다.
- expected/consensus 자동화를 구현하지 않는다.
- 실시간/분봉 시장 데이터 수집기를 만들지 않는다.
