# OpenAI 경제 해석 운영 안내서

## 1. 이 기능이 하는 일

발표 후 생성되는 CPI `canonical_release.json`을 검증하고, 결정적 수치 사실을 Python으로 계산한 뒤 OpenAI Responses API에 해석을 요청한다. 응답은 다시 검증하여 감사 정보가 포함된 `cpi-analysis-v1.json`으로 저장한다.

## 2. AI가 하는 일과 하지 않는 일

AI가 하는 일:

- 수치 의미 해석
- 직전 발표 대비 흐름 설명
- 정책 시사점 작성
- 근거와 한계 정리

AI가 하지 않는 일:

- 실제값 계산
- surprise 계산
- 시장가격 수집
- 없는 숫자 생성
- 투자 조언

## 3. 사용하는 API

- OpenAI Responses API
- Structured Outputs의 엄격한 JSON Schema
- 응답 저장을 끄는 `store: false`
- 웹 검색, 파일 검색, 함수 호출 등 외부 도구 미사용

## 4. 사용하는 모델

- 기본 모델: `gpt-5.6-sol`
- 정확성 우선 설정: `reasoning.effort`는 `high`
- 모델을 바꿀 때는 실행 환경의 `OPENAI_MODEL` 값만 변경한다.
- 기본 모델 문자열은 `scripts/providers/openai_responses.py` 한 곳에서 관리한다.

## 5. API 키

- 환경변수 이름: `OPENAI_API_KEY`
- 키를 코드, JSON, 로그, HTML, GitHub 파일에 직접 입력하지 않는다.
- 실제 운영 연결 단계에서 로컬 환경변수 또는 GitHub Secrets로 설정한다.
- canonical 파일이 없으면 키 존재 여부를 확인하지 않는다.

## 6. 실행 전 필요한 파일

기본 입력은 다음 경로의 발표 canonical 파일이다.

`data/generated/cpi/{event_id}/canonical_release.json`

실행 예:

```powershell
python scripts/analysis/generate_cpi_analysis.py --event-id US_CPI_2026_06
```

기본 출력:

`data/analysis/cpi/{event_id}/cpi-analysis-v1.json`

## 7. 상태별 의미

- `CANONICAL_RELEASE_NOT_FOUND`: 발표 canonical 파일이 없어 정상 대기한다. API 호출과 키 확인은 없다.
- `OPENAI_API_KEY_MISSING`: canonical 검증 후 실제 호출 시점에 키가 없다.
- `ALREADY_ANALYZED`: 같은 버전의 분석 파일이 이미 있어 호출하거나 덮어쓰지 않는다.
- `MODEL_REFUSAL`: 모델이 요청을 거부했으며 파일을 만들지 않는다.
- `RATE_LIMITED`: API 호출 제한 응답을 받았다. 최대 한 번만 재시도한다.
- `ANALYSIS_GENERATED`: 검증과 저장이 모두 완료됐다.

## 8. 분석 파일의 감사 정보

분석 파일에는 canonical, 프롬프트, 스키마의 SHA-256과 요청/반환 모델, 응답 ID, 토큰 사용량을 기록한다. API 키, Authorization 헤더, 전체 원본 API 응답, 모델 내부 reasoning은 기록하지 않는다.

## 9. 프롬프트 변경 방법

기존 v1 프롬프트와 결과를 덮어쓰지 않는다. 동작을 변경할 때는 v2 프롬프트, v2 스키마, 새 `analysis_version`, 새 출력 파일명을 함께 만든다. 같은 버전을 강제로 덮어쓰는 옵션은 사용하지 않는다.

## 10. 비용·보안 주의

- 실제 API 호출에는 비용이 발생한다.
- 키와 Authorization 헤더를 로그나 저장소에 올리지 않는다.
- 실행 전 모델과 예상 사용량을 확인한다.
- 429 및 일시적 서버 오류만 한 번 재시도하므로 총 호출은 최대 두 번이다.
